import { neon } from '@neondatabase/serverless';

/** Postgres error code for "relation does not exist" — i.e. init-db never ran. */
export const UNDEFINED_TABLE = '42P01';

export class MissingDatabaseUrl extends Error {
  constructor() {
    super('DATABASE_URL is not set');
    this.name = 'MissingDatabaseUrl';
  }
}

let client = null;

// Built on first use rather than at module load: an unprovisioned database then
// surfaces as a handled 503 from the request path instead of killing the
// function on cold start, which would give the browser an opaque 500.
export function db() {
  if (client) return client;

  const url = process.env.DATABASE_URL || process.env.POSTGRES_URL;
  if (!url) throw new MissingDatabaseUrl();

  client = neon(url);
  return client;
}
