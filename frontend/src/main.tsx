import "antd/dist/reset.css";
import { App as AntApp, ConfigProvider, theme } from "antd";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: "#52634e",
          colorSuccess: "#5e7a5b",
          colorWarning: "#9a742e",
          colorError: "#ac5861",
          colorInfo: "#52634e",
          colorBgBase: "#faf9f6",
          colorBgContainer: "#ffffff",
          colorBorder: "#e4e1d9",
          colorText: "#2f322d",
          colorTextSecondary: "#6b7165",
          borderRadius: 10,
          fontFamily:
            "'Segoe UI', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif",
          fontFamilyCode:
            "'JetBrains Mono', 'SFMono-Regular', Consolas, 'Liberation Mono', monospace"
        },
        components: {
          Button: {
            controlHeightLG: 46,
            primaryShadow: "none"
          },
          Input: {
            activeBorderColor: "#8f9c83",
            hoverBorderColor: "#b8c1af"
          }
        }
      }}
    >
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>
);
