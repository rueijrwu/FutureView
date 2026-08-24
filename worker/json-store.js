export function createR2JsonStore(bucket) {
  if (!bucket) throw new Error("R2 bucket binding is required");
  return {
    async getJson(key) {
      const object = await bucket.get(key);
      return object === null ? null : object.json();
    },

    async putJson(key, value) {
      await bucket.put(key, JSON.stringify(value), {
        httpMetadata: { contentType: "application/json; charset=utf-8" },
      });
      return { key };
    },

    async exists(key) {
      return (await bucket.head(key)) !== null;
    },
  };
}
