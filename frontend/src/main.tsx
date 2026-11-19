import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { App } from "./app/App";
import { AppProviders } from "./app/providers";
import "./styles.css";
import { applyTheme } from "./components/ThemeControl";

applyTheme();
const router = createBrowserRouter([{path: "*", element: <AppProviders><App/></AppProviders>}]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router}/>
  </React.StrictMode>,
);
