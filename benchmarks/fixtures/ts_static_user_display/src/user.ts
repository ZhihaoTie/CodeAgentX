export interface User {
  name: string;
  nickname?: string;
  email: string;
}

export function displayUser(user: User): string {
  return `${user.name}`;
}
