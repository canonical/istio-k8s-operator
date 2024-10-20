# The version of Istio to deploy
VERSION=1.23.2
# Directory to store the dashboard JSON files
OUTPUT_DIR="grafana_dashboards"
# Ensure the output directory exists
mkdir -p $OUTPUT_DIR

# Download all Istio dashboards
for DASHBOARD in 7639 11829 7636 7630 7645 13277; do
    REVISION="$(curl -s https://grafana.com/api/dashboards/${DASHBOARD}/revisions -s | jq ".items[] | select(.description | contains(\"${VERSION}\")) | .revision" | tail -n 1)"
    
    # Download the JSON file with a temporary name
    TEMP_FILE="$OUTPUT_DIR/dashboard_${DASHBOARD}_rev${REVISION}.json"
    curl -s https://grafana.com/api/dashboards/${DASHBOARD}/revisions/${REVISION}/download > "$TEMP_FILE"
    
    # Extract the title from the JSON and sanitize it for the filename
    TITLE=$(cat "$TEMP_FILE" | jq -r '.title' | sed 's/[ \/]/_/g')
    
    # Rename the file to include the title
    FINAL_FILE="$OUTPUT_DIR/${TITLE}_rev${REVISION}.json"
    mv "$TEMP_FILE" "$FINAL_FILE"
    
    echo "Downloaded ${TITLE} (revision ${REVISION}, id ${DASHBOARD}) to ${FINAL_FILE}..."
done

echo "All dashboards downloaded to $OUTPUT_DIR"
