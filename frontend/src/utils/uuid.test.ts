import { afterEach, expect, it, vi } from "vitest";
import { createUuid } from "./uuid";

const nativeCrypto = globalThis.crypto;
const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
afterEach(() => vi.unstubAllGlobals());

it("prefers the native secure UUID API when available", () => {
  const id = "d14fb87a-b08a-4df0-a9e1-548a900d10cb";
  const randomUUID = vi.fn(() => id);
  const getRandomValues = vi.fn();
  vi.stubGlobal("crypto", { randomUUID, getRandomValues });
  expect(createUuid()).toBe(id);
  expect(randomUUID).toHaveBeenCalledOnce();
  expect(getRandomValues).not.toHaveBeenCalled();
});

it.each([
  [0, "00000000-0000-4000-8000-000000000000"],
  [255, "ffffffff-ffff-4fff-bfff-ffffffffffff"],
])("sets the UUID v4 version and RFC variant when random bytes are %i", (byte, expected) => {
  const getRandomValues = vi.fn((buffer: Uint8Array) => buffer.fill(byte));
  vi.stubGlobal("crypto", { getRandomValues });
  expect(createUuid()).toBe(expected);
  expect(getRandomValues).toHaveBeenCalledOnce();
  expect(getRandomValues.mock.calls[0][0]).toHaveLength(16);
});

it("creates distinct correctly formatted fallback IDs using secure browser randomness", () => {
  const getRandomValues = vi.fn((buffer: Uint8Array<ArrayBuffer>) => nativeCrypto.getRandomValues(buffer));
  vi.stubGlobal("crypto", { getRandomValues });
  const ids = Array.from({ length: 256 }, () => createUuid());
  expect(ids.every(id => uuidV4.test(id))).toBe(true);
  expect(new Set(ids).size).toBe(ids.length);
  expect(getRandomValues).toHaveBeenCalledTimes(ids.length);
});

it.each([undefined, {}])("fails with a recovery message when secure randomness is unavailable", provider => {
  vi.stubGlobal("crypto", provider);
  expect(() => createUuid()).toThrow("Update your browser or open the app over HTTPS, then try again.");
});
