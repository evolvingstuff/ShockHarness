// DEF006: configuration fallbacks on process.env in every spelling; bare reads are not findings.
const port = process.env.PORT || "3000";
const host = process.env.HOST ?? "localhost";
const region = process.env["REGION"] || "eu";
const workers = Number(process.env.WORKERS || 1);
const mode = process.env.MODE === undefined ? "dev" : process.env.MODE;
const level = process.env.LEVEL ?? process.env.FALLBACK_LEVEL;
process.env.NODE_ENV ||= "development";
process.env.TZ ??= "UTC";
const { USER = "me", HOME } = process.env;

const token = process.env.TOKEN;
if (token === undefined) {
  throw new Error("TOKEN is required");
}
