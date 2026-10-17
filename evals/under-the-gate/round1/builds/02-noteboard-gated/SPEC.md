# noteboard: a notes page with an edit mode (JavaScript)

Build a single-page notes board in plain JavaScript (ES modules, no framework,
no build step): `index.html`, `app.js` and modules under `src/`.

## Behavior

- Notes are shown as a list. Clicking a note enters edit mode for it; pressing
  anywhere outside the note being edited saves it and leaves edit mode. `Escape`
  leaves edit mode without saving.
- Each note has a small toolbar with icon buttons (SVG icons inside `<button>`s):
  pin, delete. The board handles their clicks with one delegated listener on the
  list.
- Deleting a note asks for confirmation in a modal dialog. The modal is created
  when needed and attached to the page; clicking its buttons must work whether or
  not a note is being edited.
- After a save, a toast ("Saved") appears at the bottom of the page and disappears
  on its own after a few seconds; it has a close button.
- Notes persist in `localStorage`. Stored data that cannot be read is reported to
  the user once (in a toast) and the board starts empty; it is never silently
  discarded without telling the user.

## Constraints

- No dependencies at all, at run time or for tests: nothing is installed from npm.
  Tests run with `node --test`; keep the logic that can be tested without a DOM
  (storage, state, edit-mode decisions) in modules that do not touch `document`.
