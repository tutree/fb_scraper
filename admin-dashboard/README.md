# Facebook Scraper Admin Dashboard

Simple React dashboard to visualize and manage scraped Facebook leads.

## Setup

1. Install dependencies:
```bash
cd admin-dashboard
npm install
```

2. Start the development server:
```bash
npm run dev
```

The dashboard will be available at `http://localhost:3000`

## Features

- View all scraped leads in a table
- Filter by user type (Customer/Tutor/Unknown)
- Filter by status (Pending/Contacted/Not Interested/Invalid)
- Search by keyword
- Update lead status directly from the table
- View statistics dashboard with counts
- Click through to Facebook profiles and posts

## Requirements

- The FastAPI backend must be running on `http://localhost:8000`
- The backend API endpoints are proxied through Vite

## Build for Production

```bash
npm run build
```

The built files will be in the `dist` folder.
