/**
 * What `@/mocks/browser` is in every build except the test build (next.config.ts aliases it here). The production
 * bundle therefore never reaches `msw` or the mock handlers, whatever the bundler does with a dead `import()`.
 */
export async function startMockWorker(): Promise<void> {}
