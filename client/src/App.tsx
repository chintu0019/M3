// Single-pane M3. The Canvas owns everything: graph, chat, settings.
// All previous tabs have been removed — this view is the app.

import UpdateBanner from "./components/UpdateBanner";
import Canvas from "./views/Canvas";

export default function App() {
  return (
    <div className="m3-root">
      <UpdateBanner />
      <Canvas />
    </div>
  );
}
