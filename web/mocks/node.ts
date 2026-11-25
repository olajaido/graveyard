import { setupServer } from 'msw/node';
import { createMockApi, type MockApi, type MockOptions } from './handlers';

/** The MSW server of the unit tests. `vitest.setup.ts` starts it and resets it after every test. */
export const server = setupServer();

/** Install a mock API for the current test and return it for assertions. */
export function mockApi(options?: MockOptions): MockApi {
  const api = createMockApi(options);
  server.use(...api.handlers);
  return api;
}
