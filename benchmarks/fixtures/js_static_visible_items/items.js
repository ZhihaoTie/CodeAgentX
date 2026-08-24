export function visibleItems(items) {
  return items.filter((item) => !item.deleted);
}
