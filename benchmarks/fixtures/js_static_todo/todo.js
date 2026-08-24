export function toggleTodo(items, id) {
  return items.map((item) => ({
    ...item,
    completed: true,
  }));
}
