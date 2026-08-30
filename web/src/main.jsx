import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import "./index.css";
import EditorialLayout from "./layouts/EditorialLayout.jsx";
import ToolLayout from "./layouts/ToolLayout.jsx";
import Overview from "./routes/Overview.jsx";
import HowItWorks from "./routes/HowItWorks.jsx";
import Decisions from "./routes/Decisions.jsx";
import IncidentList from "./routes/IncidentList.jsx";
import IncidentDetail from "./routes/IncidentDetail.jsx";
import Evals from "./routes/Evals.jsx";
import Security from "./routes/Security.jsx";

const router = createBrowserRouter([
  {
    element: <EditorialLayout />,
    children: [
      { path: "/", element: <Overview /> },
      { path: "/how-it-works", element: <HowItWorks /> },
      { path: "/decisions", element: <Decisions /> },
    ],
  },
  {
    element: <ToolLayout />,
    children: [
      { path: "/incidents", element: <IncidentList /> },
      { path: "/incidents/:id", element: <IncidentDetail /> },
      { path: "/evals", element: <Evals /> },
      { path: "/security", element: <Security /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
);
