
const express = require('express');
const axios = require('axios');
const path = require('path');
const morgan = require('morgan');
//const { fromWeb } = require('json2csv/JSON2CSVTransform');
// import {XMLHttpRequest} from 'xmlhttprequest'

const app = express();
const port = 3663;
// const API_BASE_URL = 'http://localhost:7667';
const API_BASE_URL = 'https://api.tech-sphere.pro';
const API_API_HEADER = "274a7c568bf54ebca676fd9313360c4c";

const fs = require('fs');

// Create temp directory if it doesn't exist
const tempDir = path.join(__dirname, 'temp');
if (!fs.existsSync(tempDir)) {
  fs.mkdirSync(tempDir);
}

// Job status storage
const jobStatus = {};

// Middleware
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(morgan('dev'));
app.use(express.static(path.join(__dirname, 'public')));

// Set view engine
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));

// EJS layout middleware
app.use((req, res, next) => {
  res.locals.page = req.path;
  next();
});

// Routes
app.get('/', async (req, res) => {
  try {
      const response = await axios.get(`${API_BASE_URL}/`, {
          headers: {
               "Authorization": API_API_HEADER
          }
      });
      console.log(response);
    res.render('index', { orgs: response.data.orgs });
  } catch (error) {
    console.error('Error fetching organizations:', error);
    res.render('index', { orgs: [], error: 'Failed to fetch organizations' });
  }
});

// Route for the add organization form
app.get('/orgs/add_form', (req, res) => {
  const newOrg = {
    id: '',
    org: '',
    key: '',
    org_id: '',
    region: 'US'
  };
  res.render('edit_org_form', { org: newOrg, isAdd: true });
});

// Route to get organization details
app.get('/org/:id', async (req, res) => {
  try {
    const orgId = req.params.id;
    const refresh = req.query.refresh ? '?refresh=1' : '';

    // Try to serve the HTML file directly instead of rendering the template
    res.sendFile(path.join(__dirname, 'public', 'org_detail.html'));
  } catch (error) {
    console.error('Error serving organization detail page:', error);
    res.status(500).send('Error loading organization details');
  }
});

// API endpoint for the HTML file to fetch organization data
app.get('/api/org/:id', async (req, res) => {
  try {
    const orgId = req.params.id;
    const refresh = req.query.refresh ? '?refresh=1' : '';
    const response = await axios.get(`${API_BASE_URL}/org/${orgId}${refresh}`, {
           headers: {
                "Authorization": API_API_HEADER
           }
    });
    res.json(response.data);
  } catch (error) {
    console.error('Error fetching organization data:', error);
    res.status(500).json({ error: 'Failed to fetch organization data' });
  }
});

// Route for the edit organization form
app.get('/orgs/edit/:id', async (req, res) => {
  try {
    const orgId = req.params.id;
    const response = await axios.get(`${API_BASE_URL}/orgs/edit/${orgId}`, {
           headers: {
                "Authorization": API_API_HEADER
           }
    });
    if (response.data && response.data.org) {
      res.render('edit_org_form', {
        org: response.data.org,
        isAdd: false
      });
    } else {
      throw new Error('Organization data not found');
    }
  } catch (error) {
    console.error('Error fetching organization for editing:', error);
    res.status(404).send('Organization not found');
  }
});

// Route to get organization summary
app.get('/org/:id/summary', async (req, res) => {
  try {
    // Serve the HTML file directly
    res.sendFile(path.join(__dirname, 'public', 'org_summary.html'));
  } catch (error) {
    console.error('Error serving organization summary page:', error);
    res.status(500).send('Error loading organization summary');
  }
});

// API endpoint for the HTML file to fetch summary data
app.get('/api/org/:id/summary', async (req, res) => {
  try {
    const orgId = req.params.id;
    const refresh = req.query.refresh ? '?refresh=1' : '';

    // Detailed logging for debugging
    console.log(`Requesting summary from backend: ${API_BASE_URL}/org/${orgId}/summary${refresh}`);

    // Make the request with a longer timeout
    const response = await axios.get(`${API_BASE_URL}/org/${orgId}/summary${refresh}`, {
           headers: {
                "Authorization": API_API_HEADER
           }
    });

    // Log the summary data structure for debugging
    console.log("Received summary data with keys:", Object.keys(response.data));

    if (!response.data || !response.data.summary) {
      console.error("Invalid summary data structure:", response.data);
      return res.status(500).json({ error: 'Invalid data structure from backend' });
    }

    // Return the data from the backend
    res.json(response.data);
  } catch (error) {
    console.error('Error fetching organization summary:', error.message);

    // More detailed error information
    if (error.response) {
      // The request was made and the server responded with a status code
      // that falls out of the range of 2xx
      console.error('Backend error details:', {
        status: error.response.status,
        data: error.response.data
      });
      res.status(error.response.status).json({
        error: 'Backend error',
        message: `Error from backend: ${error.response.status}`,
        details: error.response.data
      });
    } else if (error.request) {
      // The request was made but no response was received
      console.error('No response received from backend');
      res.status(504).json({
        error: 'Backend timeout',
        message: 'No response received from backend API'
      });
    } else {
      // Something happened in setting up the request that triggered an Error
      console.error('Request setup error:', error.message);
      res.status(500).json({
        error: 'Request configuration error',
        message: error.message
      });
    }
  }
});

// Route to get cluster details
app.get('/org/:orgId/cluster/:clusterId', async (req, res) => {
  try {
    const { orgId, clusterId } = req.params;
    const response = await axios.get(`${API_BASE_URL}/org/${orgId}/cluster/${clusterId}`, {
           headers: {
                "Authorization": API_API_HEADER
           }
    });
    res.json(response.data);
  } catch (error) {
    console.error('Error fetching cluster details:', error);
    res.status(500).json({ error: 'Failed to fetch cluster details' });
  }
});

// API endpoint for the HTML file to fetch cluster details
app.get('/api/org/:orgId/cluster/:clusterId', async (req, res) => {
  try {
    const { orgId, clusterId } = req.params;
    const response = await axios.get(`${API_BASE_URL}/org/${orgId}/cluster/${clusterId}`, {
           headers: {
                "Authorization": API_API_HEADER
           }
    });
    res.json(response.data);
  } catch (error) {
    console.error('Error fetching cluster details:', error);
    res.status(500).json({ error: 'Failed to fetch cluster details' });
  }
});

// Add Organization route
app.post('/orgs', async (req, res) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/orgs`, req.body, { headers: { "Authorization": API_API_HEADER } });
    res.redirect('/');
  } catch (error) {
    console.error('Error adding organization:', error);
    res.status(500).send('Failed to add organization');
  }
});

// Edit Organization route
app.post('/orgs/edit/:id', async (req, res) => {
  try {
    const orgId = req.params.id;
    req.body.id = orgId;
    const response = await axios.post(`${API_BASE_URL}/orgs`, req.body, { headers: { "Authorization": API_API_HEADER } });
    res.redirect('/');
  } catch (error) {
    console.error('Error updating organization:', error);
    res.status(500).send('Failed to update organization');
  }
});

// Enable/Disable Organization routes
app.get('/org/disable/:id', async (req, res) => {
  try {
    const orgId = req.params.id;
    await axios.get(`${API_BASE_URL}/org/disable/${orgId}`, {
           headers: {
                "Authorization": API_API_HEADER
           }
    });
    res.redirect('/');
  } catch (error) {
    console.error('Error disabling organization:', error);
    res.status(500).send('Failed to disable organization');
  }
});

app.get('/org/enable/:id', async (req, res) => {
  try {
    const orgId = req.params.id;
    await axios.get(`${API_BASE_URL}/org/enable/${orgId}`, {
           headers: {
                "Authorization": API_API_HEADER
           }
    });
    res.redirect('/');
  } catch (error) {
    console.error('Error enabling organization:', error);
    res.status(500).send('Failed to enable organization');
  }
});

app.get('/org/:id/download_csv', async (req, res) => {
  try {
    const orgId = req.params.id;
    const refresh = req.query.refresh ? '?refresh=1' : '';

    // Get Organization Name
    const url2 = `${API_BASE_URL}/org/${orgId}${refresh ? '?refresh=1' : ''}`;
    const response2 = await axios.get(url2, {
           headers: {
                "Authorization": API_API_HEADER
           }
    });
    console.log(response2);
    const orgFullData = response2.data;
    const orgData = orgFullData.org;
    const orgName = orgData.org;
    //console.log(orgData.key)
    //const apiKey = orgData.key;

    // Make a server-side request to your CSV-generating endpoint
    // (ensure that this endpoint returns text/plain or text/csv)
    const apiUrl = `${API_BASE_URL}/org/${orgId}/download_csv`;
    const response = await axios.get(apiUrl, { responseType: 'text',
           headers: {
                "Authorization": API_API_HEADER
           }
    });
    const data = await response;
    const csvData = response.data;

    // Set headers so the browser downloads the file
    res.setHeader('Content-Type', 'text/csv');
    res.setHeader('Content-Disposition', `attachment; filename="org-${orgName}-summary.csv"`);

    res.send(csvData);
  } catch (error) {
    console.error("Error fetching CSV from summary endpoint:", error);
    res.status(500).send("Error generating CSV.");
  }
});

app.get('/org/:id/download_monthly_savings_csv', async (req, res) => {
  try {
    const orgId = req.params.id;

    // Create a job ID
    const jobId = `savings-export-${orgId}-${Date.now()}`;

    // Initialize job status
    jobStatus[jobId] = {
      status: 'processing',
      orgId: orgId,
      exportId: null,
      error: null,
      created: Date.now()
    };

    // Send immediate response with job ID
    res.json({
      status: 'processing',
      message: 'Export started. You will be notified when complete.',
      jobId: jobId
    });

    // Process the export in the background
    processSavingsExport(orgId, jobId);

  } catch (error) {
    console.error('Error starting export:', error);
    res.status(500).json({ error: 'Failed to start export process' });
  }
});

// Add a new route to check job status
app.get('/api/job-status/:jobId', (req, res) => {
  const jobId = req.params.jobId;

  // Clean up old jobs (older than 1 hour)
  const now = Date.now();
  Object.keys(jobStatus).forEach(id => {
    if (jobStatus[id].created && now - jobStatus[id].created > 3600000) {
      delete jobStatus[id];
    }
  });

  if (!jobStatus[jobId]) {
    return res.status(404).json({ error: 'Job not found' });
  }

  res.json(jobStatus[jobId]);
});

// Add route to download the completed export
app.get('/api/download/:jobId', (req, res) => {
  try {
    const jobId = req.params.jobId;

    if (!jobStatus[jobId] || !jobStatus[jobId].exportId) {
      return res.status(404).json({ error: 'Export not found or not completed' });
    }

    const exportId = jobStatus[jobId].exportId;
    const filePath = path.join(tempDir, `${exportId}.zip`);
    const orgName = jobStatus[jobId].orgName || 'organization';

    if (!fs.existsSync(filePath)) {
      return res.status(404).json({ error: 'Export file not found' });
    }

    res.download(filePath, `${orgName}-savings-analysis.zip`, (err) => {
      if (err) {
        console.error('Download error:', err);
      } else {
        // Optionally delete the file after download
        fs.unlink(filePath, (unlinkErr) => {
          if (unlinkErr) console.error('Error deleting temporary file:', unlinkErr);
        });
      }
    });
  } catch (error) {
    console.error('Error downloading export:', error);
    res.status(500).send('Failed to download export');
  }
});

// Background processing function
async function processSavingsExport(orgId, jobId) {
  try {
    // First get org info to get the name
    const orgResponse = await axios.get(`${API_BASE_URL}/org/${orgId}`, {
      headers: {
        "Authorization": API_API_HEADER
      }
    });

    const orgName = orgResponse.data.org?.org || 'organization';
    jobStatus[jobId].orgName = orgName;

    // Call the export API
    const apiUrl = `${API_BASE_URL}/org/${orgId}/download_monthly_savings_csv`;
    const response = await axios.get(apiUrl, {
      responseType: 'arraybuffer',
      headers: {
        "Authorization": API_API_HEADER
      }
    });

    // Generate export ID and save file
    const exportId = `savings-export-${orgId}-${Date.now()}`;
    const filePath = path.join(tempDir, `${exportId}.zip`);

    // Write the file
    await fs.promises.writeFile(filePath, response.data);

    // Update job status
    jobStatus[jobId].status = 'completed';
    jobStatus[jobId].exportId = exportId;

  } catch (error) {
    console.error('Export process failed:', error);

    // Update job status with error
    if (jobStatus[jobId]) {
      jobStatus[jobId].status = 'error';
      jobStatus[jobId].error = error.message || 'Export failed';
    }
  }
}

// Start server
app.listen(port, () => {
  console.log(`Frontend server running at http://localhost:${port}`);
});


