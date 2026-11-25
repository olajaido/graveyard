import { createClient, type Client } from './client';

/** The API origin, inlined at build time (ui-core UI-STK-5). An empty string means the same origin. */
export const API_URL: string = process.env.NEXT_PUBLIC_API_URL ?? '';

let shared: Client | null = null;

/** The client of the running app. Tests build their own with `createClient`. */
export function getClient(): Client {
  shared ??= createClient({ baseUrl: API_URL });
  return shared;
}
