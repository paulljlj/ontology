import { useState } from "react";
import { ReportWorkbench } from "./components/ReportWorkbench";
import { SatelliteWorkbench } from "./components/SatelliteWorkbench";
import "./satellite.css";

export function App() {
  const [mode, setMode] = useState<"satellite" | "report">("satellite");
  return <>
    <nav className="workspaceModeNav" aria-label="工作台模式">
      <span>ONTOLOGY WORKBENCH</span>
      <div>
        <button type="button" aria-pressed={mode === "satellite"} onClick={() => setMode("satellite")}>卫星网络分析</button>
        <button type="button" aria-pressed={mode === "report"} onClick={() => setMode("report")}>原有数据报表</button>
      </div>
    </nav>
    {mode === "satellite" ? <SatelliteWorkbench /> : <ReportWorkbench />}
  </>;
}
