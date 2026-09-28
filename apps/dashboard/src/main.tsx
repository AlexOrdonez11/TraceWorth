import { createRoot } from "react-dom/client";
import { App } from "./App";
import "../../../packages/ui/styles.css";
import "./workspace.css";

createRoot(document.getElementById("root")!).render(<App />);
