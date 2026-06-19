import "./i18n";
import { MapScreen } from "./MapScreen";
import { ModerationScreen } from "./ModerationScreen";

export default function App() {
  if (typeof window !== "undefined" && window.location.pathname === "/moderate") {
    return <ModerationScreen />;
  }
  return <MapScreen />;
}
