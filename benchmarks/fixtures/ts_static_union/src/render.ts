export type Result =
  | { kind: "success"; value: string }
  | { kind: "error"; message: string };

export function renderResult(result: Result): string {
  return result.value;
}
