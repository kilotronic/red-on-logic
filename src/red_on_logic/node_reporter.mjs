// A node:test reporter: one JSON object per line for each test's outcome, with its
// full title (describe blocks included), line and the first line of its failure.
// A file that failed to load shows up as a failed test named after the file, with
// the reason in that file's stderr, which is kept for it.
import path from "node:path";

function firstLine(text) {
  const line = String(text ?? "")
    .split("\n")
    .find((l) => l.trim());
  return (line ?? "").trim().slice(0, 300);
}

function failure(error) {
  const cause = error?.cause;
  if (cause && typeof cause === "object") {
    const name = cause.name ?? cause.constructor?.name ?? "Error";
    const code = cause.code ? ` [${cause.code}]` : "";
    return {
      message: `${name}${code}: ${firstLine(cause.message)}`,
      fileLevel: false,
    };
  }
  return { message: firstLine(cause ?? error?.message), fileLevel: true };
}

export default async function* reporter(source) {
  const stacks = new Map();
  const stderr = new Map();
  for await (const event of source) {
    const data = event.data ?? {};
    if (event.type === "test:stderr" && data.file) {
      const file = path.resolve(data.file);
      stderr.set(file, (stderr.get(file) ?? "") + String(data.message ?? ""));
      continue;
    }
    if (event.type === "test:start") {
      const stack = stacks.get(data.file) ?? [];
      stack.length = data.nesting;
      stack.push(data.name);
      stacks.set(data.file, stack);
      continue;
    }
    if (event.type !== "test:pass" && event.type !== "test:fail") continue;
    if (data.details?.type === "suite") continue;
    const ancestors = (stacks.get(data.file) ?? []).slice(0, data.nesting);
    const record = {
      file: data.file,
      line: data.line ?? null,
      title: data.name,
      full: [...ancestors, data.name].join(" > "),
      status:
        data.skip || data.todo
          ? "skipped"
          : event.type === "test:pass"
            ? "passed"
            : "failed",
      message: "",
      fileLevel: false,
    };
    if (record.status === "failed") {
      const { message, fileLevel } = failure(data.details?.error);
      const isFile =
        fileLevel &&
        data.nesting === 0 &&
        data.file &&
        [
          path.basename(data.file),
          path.relative(process.cwd(), data.file),
        ].includes(data.name);
      record.fileLevel = Boolean(isFile);
      record.message = isFile
        ? firstLine(
            (stderr.get(path.resolve(data.file)) ?? "")
              .split("\n")
              .find((l) => /^\s*[A-Za-z]*Error\b/.test(l)) ?? message,
          )
        : message;
    }
    yield JSON.stringify(record) + "\n";
  }
}
