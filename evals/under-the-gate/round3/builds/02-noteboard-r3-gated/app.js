// Entry point: reads the page's settings, loads the notes and mounts the board.

import { mountBoard } from "./src/board.js";
import { parseToastDuration } from "./src/config.js";
import { loadNotes } from "./src/storage.js";
import { createToaster } from "./src/toast.js";

function start(doc, storage) {
  const toaster = createToaster(
    doc,
    doc.getElementById("toasts"),
    parseToastDuration(doc.body.dataset.toastMs),
  );
  const loaded = loadNotes(storage);
  if (loaded.problem !== null) {
    toaster.show(loaded.problem, { autoHide: false });
  }
  mountBoard({
    doc,
    storage,
    list: doc.getElementById("notes"),
    addButton: doc.getElementById("add-note"),
    toaster,
    initialNotes: loaded.notes,
    newId: () => crypto.randomUUID(),
  });
}

start(document, localStorage);
