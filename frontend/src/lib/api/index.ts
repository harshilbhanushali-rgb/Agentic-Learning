/* Resolves which ApiClient the app talks to.
 *
 * This is the ONLY place the choice is made. Components and hooks call
 * `getApiClient()` and stay unaware of which implementation answered. */

import type { ApiClient, ApiMode } from './types';
import { mockClient } from './mock';
import { httpClient } from './http';

export const API_MODE: ApiMode =
  process.env.NEXT_PUBLIC_API_MODE === 'live' ? 'live' : 'mock';

export const getApiClient = (): ApiClient =>
  API_MODE === 'live' ? httpClient : mockClient;

export type { ApiClient, ApiMode, SendMessageArgs } from './types';
