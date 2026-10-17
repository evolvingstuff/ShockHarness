import { createBoard } from './src/board.js';

createBoard({
  list: document.getElementById('notes'),
  addButton: document.getElementById('add-note'),
  storage: window.localStorage,
});
