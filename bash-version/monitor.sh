HOSTS=("xxx.xxx.xx" "xxx.xxx.xx" "xxx.xxx.xx" "xxx.xxx.xx")
EMAIL="<--e-MAIL-->"
EMAIL_SECONDARY="<--e-MAIL-->"
LOG_FILE="${HOME}/neighbor_monitor.log"
STATUS_FILE="${HOME}/neighbor_monitor_status.current"
CURL_TIMEOUT=10
SLEEP_INTERVAL=120

SENDGRID_API_KEY="${SENDGRID_API_KEY:<--TOKEN-->}"
SENDER_EMAIL_API="${SENDER_EMAIL_API:<--e-MAIL-->}"
SENDGRID_API_ENDPOINT="https://api.sendgrid.com/v3/mail/send"
SENDGRID_API_HOSTNAME="api.sendgrid.com"

PUSHBULLET_TOKEN="${PUSHBULLET_TOKEN:<--TOKEN-->}"
PB_API_BASE_URL="https://api.pushbullet.com/v2/pushes"
PB_API_HOSTNAME="api.pushbullet.com"

log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" >> "${LOG_FILE}"
}

check_https() {
    local host=$1
    log_message "Checking HTTPS for ${host}..."
    HTTP_CODE=$(curl -k -s -o /dev/null -w "%{http_code}" --max-time "${CURL_TIMEOUT}" "https://${host}/")
    CURL_EXIT_CODE=$?

    if [ ${CURL_EXIT_CODE} -eq 0 ]; then
        if [ "${HTTP_CODE}" -ge 200 ] && [ "${HTTP_CODE}" -lt 500 ]; then
            echo "HTTPS_OK(${HTTP_CODE})"
        else
            echo "HTTPS_FAIL(${HTTP_CODE})"
        fi
    else
        if [ ${CURL_EXIT_CODE} -eq 28 ]; then
            echo "HTTPS_FAIL(TIMEOUT)"
        elif [ ${CURL_EXIT_CODE} -eq 6 ]; then
            echo "HTTPS_FAIL(DNS_FAIL_OR_CONN_REFUSED)"
        else
            echo "HTTPS_FAIL(CURL_ERROR_${CURL_EXIT_CODE})"
        fi
    fi
}

send_api_email() {
    local recipient_email=$1
    local subject=$2
    local body=$3

    log_message "Attempting to send email to ${recipient_email} with subject '${subject}'"

    if ! command -v jq &> /dev/null; then
        log_message "Error: 'jq' is not installed. Cannot send email. Please install 'jq' (e.g., sudo apt-get install jq)."
        return 1
    fi

    JSON_PAYLOAD=$(jq -n \
        --arg to_email "$recipient_email" \
        --arg from_email "$SENDER_EMAIL_API" \
        --arg subj "$subject" \
        --arg content_val "$body" \
        '{
          "personalizations": [
            {
              "to": [
                {
                  "email": $to_email
                }
              ]
            }
          ],
          "from": {
            "email": $from_email
          },
          "subject": $subj,
          "content": [
            {
              "type": "text/plain",
              "value": $content_val
            }
          ]
        }')

    RESPONSE=$(curl -s -X POST "${SENDGRID_API_ENDPOINT}" \
        -H "Host: ${SENDGRID_API_HOSTNAME}" \
        -H "Authorization: Bearer ${SENDGRID_API_KEY}" \
        -H "Content-Type: application/json" \
        -d "${JSON_PAYLOAD}" \
        -k \
        --max-time "${CURL_TIMEOUT}" \
        -w "%{http_code}" \
        2>/dev/null)

    HTTP_CODE="${RESPONSE: -3}"
    BODY_RESPONSE="${RESPONSE:0:${#RESPONSE}-3}"

    if [ "${HTTP_CODE}" -ge 200 ] && [ "${HTTP_CODE}" -lt 300 ]; then
        log_message "API Email sent successfully to ${recipient_email}."
        return 0
    else
        log_message "HTTP Error sending email to ${recipient_email}: HTTP ${HTTP_CODE}. Response: ${BODY_RESPONSE}"
        return 1
    fi
}

send_pushbullet_notification() {
    local title=$1
    local body=$2

    log_message "Attempting to send Pushbullet notification with title '${title}'"

    if ! command -v jq &> /dev/null; then
        log_message "Error: 'jq' is not installed. Cannot send Pushbullet notification. Please install 'jq' (e.g., sudo apt-get install jq)."
        return 1
    fi

    JSON_PAYLOAD=$(jq -n \
        --arg type "note" \
        --arg title_val "$title" \
        --arg body_val "$body" \
        '{
          "type": $type,
          "title": $title_val,
          "body": $body_val
        }')

    RESPONSE=$(curl -s -X POST "${PB_API_BASE_URL}" \
        -u "${PUSHBULLET_TOKEN}:" \
        -H "Host: ${PB_API_HOSTNAME}" \
        -H "Content-Type: application/json" \
        -d "${JSON_PAYLOAD}" \
        -k \
        --max-time "${CURL_TIMEOUT}" \
        -w "%{http_code}" \
        2>/dev/null)

    HTTP_CODE="${RESPONSE: -3}"
    BODY_RESPONSE="${RESPONSE:0:${#RESPONSE}-3}"

    if [ "${HTTP_CODE}" -ge 200 ] && [ "${HTTP_CODE}" -lt 300 ]; then
        log_message "Pushbullet notification sent successfully."
        return 0
    else
        log_message "HTTP Error sending Pushbullet: HTTP ${HTTP_CODE}. Response: ${BODY_RESPONSE}"
        return 1
    fi
}

main() {
    log_message "Script started."

    if [ ! -f "${STATUS_FILE}" ]; then
        log_message "Status file '${STATUS_FILE}' not found. Initializing with 'OK'."
        echo "OK" > "${STATUS_FILE}"
    fi

    while true; do
        log_message "Starting new monitoring cycle..."

        previous_overall_status=$(cat "${STATUS_FILE}" 2>/dev/null || echo "UNKNOWN")
        if [ "${previous_overall_status}" == "" ]; then
            previous_overall_status="UNKNOWN"
        fi

        current_failures=0
        report="Neighbor Host Status Report\n$(date '+%Y-%m-%d %H:%M:%S')\n\n"
        declare -A host_status_map

        for host in "${HOSTS[@]}"; do
            https_status=$(check_https "${host}")
            host_status_map["${host}"]="HTTPS: ${https_status}"
            report+="• ${host}: ${host_status_map["${host}"]}\n"

            if [[ "${https_status}" == *"FAIL"* ]]; then
                current_failures=$((current_failures + 1))
            fi
        done

        current_overall_status="OK"
        if [ "${current_failures}" -gt 0 ]; then
            current_overall_status="FAIL"
        fi

        log_message "${report}"

        if [ "${current_overall_status}" != "${previous_overall_status}" ]; then
            log_message "Status changed from ${previous_overall_status} to ${current_overall_status}. Sending notifications."

            send_api_email "${EMAIL}" "[STATUS CHANGE] Neighbor Host - From ${previous_overall_status} to ${current_overall_status}" "${report}"
            send_api_email "${EMAIL_SECONDARY}" "[ALERT] System Issues on HTTPD ALL" "HTTPD MONITOR ALERT FROM ALL"
            send_pushbullet_notification "Host Monitor Alert: ${current_overall_status}" "Status changed from ${previous_overall_status} to ${current_overall_status}.\n\n${report}"

            echo "${current_overall_status}" > "${STATUS_FILE}"
        else
            log_message "Status remains ${current_overall_status}. No new notification sent."
        fi

        log_message "Monitoring cycle finished. Sleeping for ${SLEEP_INTERVAL} seconds..."
        sleep "${SLEEP_INTERVAL}"
    done
}

main
