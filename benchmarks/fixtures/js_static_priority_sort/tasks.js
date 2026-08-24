export function sortTasks(tasks) {
  return tasks.sort((left, right) => left.createdAt - right.createdAt);
}
