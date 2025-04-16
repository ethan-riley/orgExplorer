# BackEnd: Org Explorer API

## Overview

**Org Explorer API** is a Flask-based backend for managing organizations and fetching cluster data. It supports generating detailed monthly savings and resource cost reports based on cluster data. The API uses a SQLite database (`orgs.db`) to store organization data and cache responses, speeding up repeated requests.

## Features

- **Organization Management:**  
  - Load organization details from a CSV file into a SQLite database.
  - Perform CRUD operations on organizations.

- **Cluster Data Retrieval:**  
  - Fetch cluster summaries and detailed cluster info via external API calls.
  - Retrieve and cache data to reduce redundant API calls.

- **Monthly Savings Report Generation:**  
  - Integrates with `monthlySavingsReport.py` to generate two reports:
    - **Monthly Savings Report:** Savings computed per cluster and month.
    - **Resource Cost Report:** Detailed resource usage cost calculations.
  - Provides endpoints to return reports in JSON format and download them as CSV (packaged in a zip file).

- **Caching Mechanism:**  
  - Cached responses are saved in the `cache` table in `orgs.db` using a unique key (e.g., `"monthly_savings_report"`) per organization.
  - The caching helps avoid repetitive computation when the same data is requested multiple times.

## API Endpoints

- **GET `/`**  
  Returns a simple list of all organizations.

- **GET `/orgs` (GET/POST)**  
  Manage organizations (list, add, or update).

- **GET `/org/<int:org_db_id>`**  
  Returns the cluster list for a given organization.

- **GET `/org/<int:org_db_id>/cluster/<cluster_id>`**  
  Returns detailed info for a specified cluster.

- **GET `/org/<int:org_db_id>/summary`**  
  Returns a summary of cluster statistics (like production clusters, CPU usage, etc.).

- **GET `/org/<int:org_db_id>/download_csv`**  
  Downloads the full cluster details as a CSV.

- **GET `/org/<int:org_db_id>/monthly_savings`**  
  Returns the monthly savings and resource cost reports in JSON format.  
  This endpoint uses caching to avoid repeated generation.

- **GET `/org/<int:org_db_id>/download_monthly_savings_csv`**  
  Generates CSV files from the cached monthly savings reports, packages them into a zip file, and sends it as a download.

## Setup & Installation

### Prerequisites

- Python 3.7+
- Virtual environment tool (optional but recommended)
- Required Python packages: Flask, requests, pandas, etc.

### Installation Steps

1. **Clone the Repository:**

   ```bash
   git clone <repository_url>
   cd <repository_directory>
   ```

2. **Create and Activate a Virtual Environment:**

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Linux/macOS
   venv\Scripts\activate     # On Windows
   ```

3. **Install Dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

   *(Make sure your requirements.txt includes Flask, pandas, requests, etc.)*

4. **Prepare Organization Data:**

   - Place an `orgs.csv` file at the project root. This file should contain columns like `org`, `key`, `org_id`, etc.
   - The application automatically loads and caches organization data into the SQLite database (`orgs.db`).

## Running the Application

To start the Flask API server, run:

```bash
python app.py
```

The API will be available at [http://localhost:7667](http://localhost:7667).

## Usage Examples

- **Retrieve Monthly Savings Report (JSON):**

  ```bash
  curl "http://localhost:7667/org/1/monthly_savings"
  ```

- **Download Monthly Savings Report (CSV Zip):**

  ```bash
  curl "http://localhost:7667/org/1/download_monthly_savings_csv" --output monthly_savings_report.zip
  ```

## Caching Details

- **Location:**  
  The cache is stored in the SQLite database file (`orgs.db`), within the `cache` table.

- **Mechanism:**  
  The helper functions `get_cache(org_id, action)` and `set_cache(org_id, action, data)` are used to read from and write to the cache.  
  For example, the monthly savings report uses the cache key `"monthly_savings_report"` so that when the same organization requests the report, the already computed data is returned immediately.

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request for any bug fixes or feature improvements.  
For major changes, please open an issue first to discuss what you would like to change.

## License

This project is licensed under the MIT License – see the [LICENSE](LICENSE) file for details.

# FrontEnd: Organization Dashboard

This project is a simple web-based dashboard for viewing an organization's summary and clusters. It includes functionality to display summary details, list clusters, view individual cluster information, and download reports (such as a ZIP file containing a savings analysis).

## Features

- **Organization Summary Page**  
  View detailed organization information and summary statistics with a neatly formatted table.

- **Organization Clusters Page**  
  View a list of clusters associated with an organization, filter results by cluster ID, name, or account ID, and view detailed cluster information upon clicking a row.

- **Download Reports**  
  Download reports in CSV or ZIP format. The ZIP download, for example, is used for downloading a savings analysis package.

- **Responsive Design**  
  Leverages Bootstrap 5 and FontAwesome for a responsive and modern user interface.

- **API Integration**  
  Uses AJAX (`fetch`) and dynamic URL assignment to interact with backend REST API endpoints.

## FrontEnd Structure

```
├── public
│   ├── css
│   │   └── style.css       # Custom styles (may override some Bootstrap defaults)
│   └── js
│       └── main.js         # (Optional) external JavaScript if you choose to separate inline scripts
├── views
│   ├── org_detail.html     # Organization clusters & details view
│   └── org_summary.html    # Organization summary view
├── server.js               # Express server (handles API endpoints and serving the views)
├── package.json            # Node.js project configuration
└── README.md               # This file
```

## Setup and Installation

### Prerequisites

- [Node.js](https://nodejs.org/) (v14+ recommended)
- [npm](https://www.npmjs.com/) or [Yarn](https://yarnpkg.com/)

### Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/yourusername/organization-dashboard.git
   cd organization-dashboard
   ```

2. **Install dependencies:**

   ```bash
   npm install
   ```

3. **Configuration:**

   - Ensure you have set your API base URL (for example, in a configuration file or as an environment variable) so that the JavaScript can call your API endpoints correctly.

4. **Run the server:**

   ```bash
   npm start
   ```

   The server will start on the configured port (e.g., [http://localhost:3000](http://localhost:3000)).

## Usage

- **Viewing Organization Summary:**  
  Navigate to `/org/:id/summary` (replace `:id` with the specific organization ID) to see the organization summary. This page loads data dynamically from `/api/org/:id/summary` using AJAX.

- **Viewing Organization Clusters:**  
  Navigate to `/org/:id` to view clusters associated with the organization. The page includes a search filter to quickly find clusters by ID, name, or account ID. Clicking on a cluster row loads detailed information via an API call to `/api/org/:orgId/cluster/:clusterId`.

- **Downloading Reports:**  
  - **Summary Page:**  
    The download button on the summary page will fetch a ZIP file from the endpoint `/org/:id/download_zip` (ensure your backend serves this endpoint with the appropriate `Content-Disposition` header).  
  - **Clusters Page:**  
    The "Download Savings Analysis" button on the clusters page was initially linked to a CSV endpoint. It has been updated to point to the ZIP download endpoint.

## Customization

- **Modifying Styles:**  
  You can override default Bootstrap styles by editing `public/css/style.css`.
  
- **Adjusting API Endpoints:**  
  If your backend API endpoints differ from the ones in the JavaScript code, update the URLs in the inline scripts or external JavaScript file accordingly.

- **JavaScript Functionality:**  
  The current inline JavaScript (in the HTML views) handles loading of data and dynamic URL generation. For a larger project, consider moving these scripts to separate files in `public/js`.

## Troubleshooting

- **Button Alignment Issues:**  
  If button layout is not as expected, check for any conflicting CSS rules (especially within `public/css/style.css`) that may override Bootstrap defaults. Use your browser's developer tools to inspect styles.

- **Download Not Triggering:**  
  Verify that the endpoint `/org/:id/download_zip` exists on your server and that it sends the appropriate headers (i.e., `Content-Disposition` set as an attachment).

- **API Errors:**  
  Use your browser console to inspect fetch requests and responses in order to debug any API connectivity issues.

## Contributing

Feel free to submit issues or pull requests if you have any improvements or suggestions.

1. Fork the repository.
2. Create a new branch: `git checkout -b feature/your-feature-name`.
3. Commit your changes: `git commit -am 'Add some feature'`.
4. Push to the branch: `git push origin feature/your-feature-name`.
5. Submit a pull request.

## License

This project is licensed under the [MIT License](LICENSE).
