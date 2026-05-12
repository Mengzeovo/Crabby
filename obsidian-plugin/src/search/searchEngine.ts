export type SearchSort = "score" | "mtime_desc" | "mtime_asc" | "path";

export interface SearchInput {
  query: string;
  max_results?: number;
  context_chars?: number;
  sort?: SearchSort;
}

export interface SearchDocument {
  path: string;
  name: string;
  ext: string;
  content: string;
  mtime: number;
  ctime?: number;
  tags?: string[];
  aliases?: string[];
  properties?: Record<string, unknown>;
  sections?: SearchTextPart[];
  blocks?: SearchTextPart[];
  tasks?: SearchTaskPart[];
}

export interface SearchTextPart {
  text: string;
  line?: number;
}

export interface SearchTaskPart extends SearchTextPart {
  status: "todo" | "done";
}

export interface SearchMatch {
  field: string;
  text: string;
  line?: number;
  start?: number;
  end?: number;
}

export interface SearchResultItem {
  path: string;
  ext: string;
  score: number;
  matches: SearchMatch[];
  snippet: string;
  field: string;
  line?: number;
  tags: string[];
  aliases: string[];
  mtime: number;
  truncated: boolean;
}

export interface SearchResponse {
  query: string;
  results: SearchResultItem[];
  total_matches: number;
  truncated: boolean;
}

type TokenType =
  | "term"
  | "phrase"
  | "regex"
  | "field"
  | "property"
  | "or"
  | "not"
  | "lparen"
  | "rparen";

interface Token {
  type: TokenType;
  value: string;
  flags?: string;
}

type SearchNode =
  | { type: "empty" }
  | { type: "term"; value: string; exact: boolean }
  | { type: "regex"; pattern: string; flags: string }
  | { type: "not"; child: SearchNode }
  | { type: "and"; children: SearchNode[] }
  | { type: "or"; children: SearchNode[] }
  | { type: "field"; field: string; child: SearchNode }
  | { type: "property"; raw: string };

interface EvalOptions {
  matchCase: boolean;
}

interface EvalResult {
  ok: boolean;
  matches: SearchMatch[];
  score: number;
}

const FIELD_OPERATORS = new Set([
  "file",
  "path",
  "content",
  "tag",
  "line",
  "block",
  "section",
  "task",
  "task-todo",
  "task-done",
  "match-case",
  "ignore-case",
]);

export function searchDocuments(
  documents: SearchDocument[],
  input: SearchInput,
): SearchResponse {
  const query = input.query.trim();
  const maxResults = clampInt(input.max_results ?? 20, 1, 100);
  const contextChars = clampInt(input.context_chars ?? 160, 0, 1000);
  const sort = input.sort ?? "score";

  if (!query) {
    return { query, results: [], total_matches: 0, truncated: false };
  }

  const ast = parseSearchQuery(query);
  const matches: SearchResultItem[] = [];

  for (const doc of documents) {
    const result = evaluateNode(ast, doc, { matchCase: false });
    if (!result.ok) {
      continue;
    }

    const firstMatch = result.matches[0] ?? {
      field: "content",
      text: doc.content,
    };
    matches.push({
      path: doc.path,
      ext: doc.ext,
      score: Math.round(result.score * 100) / 100,
      matches: result.matches.slice(0, 8),
      snippet: makeSnippet(doc, firstMatch, contextChars),
      field: firstMatch.field,
      line: firstMatch.line,
      tags: normalizeStringList(doc.tags),
      aliases: normalizeStringList(doc.aliases),
      mtime: doc.mtime,
      truncated: result.matches.length > 8,
    });
  }

  sortResults(matches, sort);
  const totalMatches = matches.length;
  const results = matches.slice(0, maxResults);
  return {
    query,
    results,
    total_matches: totalMatches,
    truncated: totalMatches > results.length,
  };
}

export function parseSearchQuery(query: string): SearchNode {
  const tokens = tokenize(query);
  const parser = new Parser(tokens);
  return parser.parseExpression();
}

function tokenize(query: string): Token[] {
  const tokens: Token[] = [];
  let index = 0;

  while (index < query.length) {
    const char = query[index];
    if (/\s/.test(char)) {
      index += 1;
      continue;
    }
    if (char === "(") {
      tokens.push({ type: "lparen", value: char });
      index += 1;
      continue;
    }
    if (char === ")") {
      tokens.push({ type: "rparen", value: char });
      index += 1;
      continue;
    }
    if (char === "-") {
      tokens.push({ type: "not", value: char });
      index += 1;
      continue;
    }
    if (char === '"') {
      const parsed = readQuoted(query, index);
      tokens.push({ type: "phrase", value: parsed.value });
      index = parsed.next;
      continue;
    }
    if (char === "/") {
      const parsed = readRegex(query, index);
      tokens.push({
        type: "regex",
        value: parsed.value,
        flags: parsed.flags,
      });
      index = parsed.next;
      continue;
    }
    if (char === "[") {
      const parsed = readBracket(query, index);
      tokens.push({ type: "property", value: parsed.value });
      index = parsed.next;
      continue;
    }

    const field = readFieldOperator(query, index);
    if (field) {
      tokens.push({ type: "field", value: field.value });
      index = field.next;
      continue;
    }

    const parsed = readWord(query, index);
    const value = parsed.value;
    tokens.push({
      type: value === "OR" ? "or" : "term",
      value,
    });
    index = parsed.next;
  }

  return tokens;
}

class Parser {
  private index = 0;

  constructor(private readonly tokens: Token[]) {}

  parseExpression(): SearchNode {
    return this.parseOr();
  }

  private parseOr(): SearchNode {
    const children = [this.parseAnd()];
    while (this.match("or")) {
      children.push(this.parseAnd());
    }
    return children.length === 1 ? children[0] : { type: "or", children };
  }

  private parseAnd(): SearchNode {
    const children: SearchNode[] = [];
    while (!this.isAtEnd() && !this.check("rparen") && !this.check("or")) {
      children.push(this.parseUnary());
    }
    if (children.length === 0) {
      return { type: "empty" };
    }
    return children.length === 1 ? children[0] : { type: "and", children };
  }

  private parseUnary(): SearchNode {
    if (this.match("not")) {
      return { type: "not", child: this.parseUnary() };
    }
    return this.parsePrimary();
  }

  private parsePrimary(): SearchNode {
    const token = this.advance();
    if (!token) {
      return { type: "empty" };
    }

    if (token.type === "lparen") {
      const expression = this.parseExpression();
      this.match("rparen");
      return expression;
    }

    if (token.type === "field") {
      return {
        type: "field",
        field: token.value,
        child: this.parseUnary(),
      };
    }

    if (token.type === "property") {
      return { type: "property", raw: token.value };
    }

    if (token.type === "phrase") {
      return { type: "term", value: token.value, exact: true };
    }

    if (token.type === "regex") {
      return { type: "regex", pattern: token.value, flags: token.flags ?? "" };
    }

    if (token.type === "term") {
      return { type: "term", value: token.value, exact: false };
    }

    return { type: "empty" };
  }

  private match(type: TokenType): boolean {
    if (!this.check(type)) {
      return false;
    }
    this.index += 1;
    return true;
  }

  private check(type: TokenType): boolean {
    return this.tokens[this.index]?.type === type;
  }

  private advance(): Token | undefined {
    return this.tokens[this.index++];
  }

  private isAtEnd(): boolean {
    return this.index >= this.tokens.length;
  }
}

function evaluateNode(
  node: SearchNode,
  doc: SearchDocument,
  options: EvalOptions,
): EvalResult {
  switch (node.type) {
    case "empty":
      return { ok: true, matches: [], score: 0 };
    case "term":
      return evaluateDefaultTerm(node.value, doc, options, node.exact);
    case "regex":
      return evaluateDefaultRegex(node.pattern, node.flags, doc, options);
    case "not": {
      const child = evaluateNode(node.child, doc, options);
      return { ok: !child.ok, matches: [], score: 0 };
    }
    case "and": {
      const allMatches: SearchMatch[] = [];
      let score = 0;
      for (const child of node.children) {
        const result = evaluateNode(child, doc, options);
        if (!result.ok) {
          return { ok: false, matches: [], score: 0 };
        }
        allMatches.push(...result.matches);
        score += result.score;
      }
      return { ok: true, matches: allMatches, score };
    }
    case "or": {
      const allMatches: SearchMatch[] = [];
      let score = 0;
      for (const child of node.children) {
        const result = evaluateNode(child, doc, options);
        if (result.ok) {
          allMatches.push(...result.matches);
          score += result.score;
        }
      }
      return { ok: allMatches.length > 0 || score > 0, matches: allMatches, score };
    }
    case "field":
      return evaluateField(node.field, node.child, doc, options);
    case "property":
      return evaluateProperty(node.raw, doc, options);
  }
}

function evaluateField(
  field: string,
  child: SearchNode,
  doc: SearchDocument,
  options: EvalOptions,
): EvalResult {
  if (field === "match-case") {
    return evaluateNode(child, doc, { ...options, matchCase: true });
  }
  if (field === "ignore-case") {
    return evaluateNode(child, doc, { ...options, matchCase: false });
  }
  if (field === "file") {
    return evaluateTextNode(child, `${doc.name}\n${basename(doc.name)}`, "file", doc, options, 1.4);
  }
  if (field === "path") {
    return evaluateTextNode(child, doc.path, "path", doc, options, 1.2);
  }
  if (field === "content") {
    return evaluateTextNode(child, doc.content, "content", doc, options, 1);
  }
  if (field === "tag") {
    return evaluateTag(child, doc, options);
  }
  if (field === "line") {
    return evaluateParts(child, getLines(doc), "line", doc, options, 1.1);
  }
  if (field === "block") {
    return evaluateParts(child, getBlocks(doc), "block", doc, options, 1.1);
  }
  if (field === "section") {
    return evaluateParts(child, getSections(doc), "section", doc, options, 1.2);
  }
  if (field === "task") {
    return evaluateParts(child, getTasks(doc), "task", doc, options, 1.3);
  }
  if (field === "task-todo") {
    return evaluateParts(
      child,
      getTasks(doc).filter((task) => task.status === "todo"),
      "task-todo",
      doc,
      options,
      1.4,
    );
  }
  if (field === "task-done") {
    return evaluateParts(
      child,
      getTasks(doc).filter((task) => task.status === "done"),
      "task-done",
      doc,
      options,
      1.4,
    );
  }
  return evaluateNode(child, doc, options);
}

function evaluateDefaultTerm(
  value: string,
  doc: SearchDocument,
  options: EvalOptions,
  exact: boolean,
): EvalResult {
  const contentMatches = findTermMatches(doc.content, value, "content", options, exact);
  contentMatches.forEach((match) => {
    if (match.start !== undefined) {
      match.line = lineForOffset(doc.content, match.start);
    }
  });

  const fileMatches = findTermMatches(doc.name, value, "file", options, exact);
  const pathMatches = findTermMatches(doc.path, value, "path", options, exact);
  const matches = [...fileMatches, ...pathMatches, ...contentMatches];
  return {
    ok: matches.length > 0,
    matches,
    score: fileMatches.length * 2 + pathMatches.length * 1.2 + contentMatches.length,
  };
}

function evaluateDefaultRegex(
  pattern: string,
  flags: string,
  doc: SearchDocument,
  options: EvalOptions,
): EvalResult {
  const contentMatches = findRegexMatches(doc.content, pattern, flags, "content", options);
  contentMatches.forEach((match) => {
    if (match.start !== undefined) {
      match.line = lineForOffset(doc.content, match.start);
    }
  });
  const pathMatches = findRegexMatches(doc.path, pattern, flags, "path", options);
  const fileMatches = findRegexMatches(doc.name, pattern, flags, "file", options);
  const matches = [...fileMatches, ...pathMatches, ...contentMatches];
  return {
    ok: matches.length > 0,
    matches,
    score: fileMatches.length * 2 + pathMatches.length * 1.2 + contentMatches.length,
  };
}

function evaluateTextNode(
  child: SearchNode,
  text: string,
  field: string,
  source: SearchDocument,
  options: EvalOptions,
  weight: number,
  line?: number,
): EvalResult {
  const doc: SearchDocument = {
    ...source,
    content: text,
    path: "",
    name: "",
    tags: [],
    aliases: [],
    properties: {},
    sections: [],
    blocks: [],
    tasks: [],
  };
  const result = evaluateNode(child, doc, options);
  if (!result.ok) {
    return result;
  }
  return {
    ok: true,
    matches: result.matches.map((match) => ({
      ...match,
      field,
      line: line ?? match.line,
    })),
    score: result.score * weight,
  };
}

function evaluateParts(
  child: SearchNode,
  parts: SearchTextPart[],
  field: string,
  doc: SearchDocument,
  options: EvalOptions,
  weight: number,
): EvalResult {
  const matches: SearchMatch[] = [];
  let score = 0;
  for (const part of parts) {
    const result = evaluateTextNode(
      child,
      part.text,
      field,
      doc,
      options,
      weight,
      part.line,
    );
    if (result.ok) {
      matches.push(...result.matches);
      score += result.score;
    }
  }
  return { ok: matches.length > 0, matches, score };
}

function evaluateTag(
  child: SearchNode,
  doc: SearchDocument,
  options: EvalOptions,
): EvalResult {
  const tags = normalizeStringList(doc.tags);
  if (child.type === "term") {
    const query = normalizeTag(child.value);
    const matches = tags
      .filter((tag) => tagMatches(tag, query, options.matchCase))
      .map((tag) => ({ field: "tag", text: tag }));
    return { ok: matches.length > 0, matches, score: matches.length * 2 };
  }
  return evaluateTextNode(child, tags.join("\n"), "tag", doc, options, 2);
}

function evaluateProperty(
  raw: string,
  doc: SearchDocument,
  options: EvalOptions,
): EvalResult {
  const parsed = parsePropertyQuery(raw);
  const properties = doc.properties ?? {};
  const key = parsed.key;
  const value = getPropertyValue(properties, key);
  const exists = value !== undefined;

  if (!exists) {
    return { ok: false, matches: [], score: 0 };
  }
  if (parsed.value === null) {
    return {
      ok: true,
      matches: [{ field: "property", text: key }],
      score: 2,
    };
  }

  const serialized = serializePropertyValue(value);
  if (parsed.value.trim().toLowerCase() === "null") {
    const empty = serialized.trim() === "";
    return {
      ok: empty,
      matches: empty ? [{ field: "property", text: `${key}: null` }] : [],
      score: empty ? 2 : 0,
    };
  }

  const comparison = comparePropertyValue(value, parsed.value);
  if (comparison !== null) {
    return {
      ok: comparison,
      matches: comparison
        ? [{ field: "property", text: `${key}: ${serialized}` }]
        : [],
      score: comparison ? 2 : 0,
    };
  }

  const node = parseSearchQuery(parsed.value);
  const result = evaluateTextNode(node, serialized, "property", doc, options, 2);
  return result.ok
    ? {
        ok: true,
        matches: result.matches.map((match) => ({
          ...match,
          text: `${key}: ${match.text}`,
        })),
        score: result.score,
      }
    : result;
}

function findTermMatches(
  text: string,
  term: string,
  field: string,
  options: EvalOptions,
  exact: boolean,
): SearchMatch[] {
  const query = exact ? term : term.trim();
  if (!query) {
    return [];
  }

  const haystack = options.matchCase ? text : text.toLowerCase();
  const needle = options.matchCase ? query : query.toLowerCase();
  const matches: SearchMatch[] = [];
  let start = haystack.indexOf(needle);
  while (start !== -1 && matches.length < 20) {
    const end = start + needle.length;
    matches.push({
      field,
      text: text.slice(start, end),
      start,
      end,
    });
    start = haystack.indexOf(needle, Math.max(end, start + 1));
  }
  return matches;
}

function findRegexMatches(
  text: string,
  pattern: string,
  flags: string,
  field: string,
  options: EvalOptions,
): SearchMatch[] {
  try {
    const nextFlags = new Set(flags.split(""));
    nextFlags.add("g");
    if (!options.matchCase) {
      nextFlags.add("i");
    }
    const regex = new RegExp(pattern, Array.from(nextFlags).join(""));
    const matches: SearchMatch[] = [];
    let match: RegExpExecArray | null;
    while ((match = regex.exec(text)) && matches.length < 20) {
      const value = match[0];
      matches.push({
        field,
        text: value,
        start: match.index,
        end: match.index + value.length,
      });
      if (value.length === 0) {
        regex.lastIndex += 1;
      }
    }
    return matches;
  } catch {
    return [];
  }
}

function makeSnippet(
  doc: SearchDocument,
  match: SearchMatch,
  contextChars: number,
): string {
  if (contextChars === 0) {
    return "";
  }
  if (match.line !== undefined) {
    const line = doc.content.split(/\r?\n/)[match.line - 1];
    if (line) {
      return trimSnippet(line, contextChars);
    }
  }
  if (match.start !== undefined && match.end !== undefined && match.field === "content") {
    const start = Math.max(0, match.start - contextChars);
    const end = Math.min(doc.content.length, match.end + contextChars);
    return trimSnippet(doc.content.slice(start, end).replace(/\s+/g, " "), contextChars * 2);
  }
  return trimSnippet(match.text || doc.path, contextChars * 2);
}

function getLines(doc: SearchDocument): SearchTextPart[] {
  return doc.content.split(/\r?\n/).map((text, index) => ({
    text,
    line: index + 1,
  }));
}

function getBlocks(doc: SearchDocument): SearchTextPart[] {
  if (doc.blocks?.length) {
    return doc.blocks;
  }
  return doc.content
    .split(/\n\s*\n/g)
    .map((text) => text.trim())
    .filter(Boolean)
    .map((text) => ({ text }));
}

function getSections(doc: SearchDocument): SearchTextPart[] {
  if (doc.sections?.length) {
    return doc.sections;
  }
  return [{ text: doc.content, line: 1 }];
}

function getTasks(doc: SearchDocument): SearchTaskPart[] {
  if (doc.tasks?.length) {
    return doc.tasks;
  }
  const tasks: SearchTaskPart[] = [];
  doc.content.split(/\r?\n/).forEach((line, index) => {
    const match = /^\s*[-*]\s+\[([^\]])\]\s+(.*)$/.exec(line);
    if (match) {
      tasks.push({
        text: line,
        line: index + 1,
        status: match[1] === " " ? "todo" : "done",
      });
    }
  });
  return tasks;
}

function sortResults(results: SearchResultItem[], sort: SearchSort): void {
  results.sort((a, b) => {
    if (sort === "mtime_desc") {
      return b.mtime - a.mtime || a.path.localeCompare(b.path);
    }
    if (sort === "mtime_asc") {
      return a.mtime - b.mtime || a.path.localeCompare(b.path);
    }
    if (sort === "path") {
      return a.path.localeCompare(b.path);
    }
    return b.score - a.score || b.mtime - a.mtime || a.path.localeCompare(b.path);
  });
}

function readQuoted(text: string, start: number): { value: string; next: number } {
  let value = "";
  let index = start + 1;
  while (index < text.length) {
    const char = text[index];
    if (char === "\\" && index + 1 < text.length) {
      value += text[index + 1];
      index += 2;
      continue;
    }
    if (char === '"') {
      return { value, next: index + 1 };
    }
    value += char;
    index += 1;
  }
  return { value, next: index };
}

function readRegex(
  text: string,
  start: number,
): { value: string; flags: string; next: number } {
  let value = "";
  let index = start + 1;
  while (index < text.length) {
    const char = text[index];
    if (char === "\\" && index + 1 < text.length) {
      value += char + text[index + 1];
      index += 2;
      continue;
    }
    if (char === "/") {
      index += 1;
      let flags = "";
      while (index < text.length && /[a-z]/i.test(text[index])) {
        flags += text[index];
        index += 1;
      }
      return { value, flags, next: index };
    }
    value += char;
    index += 1;
  }
  return { value, flags: "", next: index };
}

function readBracket(text: string, start: number): { value: string; next: number } {
  let value = "";
  let index = start + 1;
  while (index < text.length && text[index] !== "]") {
    value += text[index];
    index += 1;
  }
  return { value, next: Math.min(index + 1, text.length) };
}

function readWord(text: string, start: number): { value: string; next: number } {
  let index = start;
  while (index < text.length && !/\s/.test(text[index]) && !/[()]/.test(text[index])) {
    index += 1;
  }
  return { value: text.slice(start, index), next: index };
}

function readFieldOperator(
  text: string,
  start: number,
): { value: string; next: number } | null {
  const match = /^[A-Za-z-]+:/.exec(text.slice(start));
  if (!match) {
    return null;
  }
  const value = match[0].slice(0, -1);
  if (!FIELD_OPERATORS.has(value)) {
    return null;
  }
  return { value, next: start + match[0].length };
}

function parsePropertyQuery(raw: string): { key: string; value: string | null } {
  const index = raw.indexOf(":");
  if (index === -1) {
    return { key: raw.trim(), value: null };
  }
  return {
    key: raw.slice(0, index).trim(),
    value: raw.slice(index + 1).trim(),
  };
}

function getPropertyValue(
  properties: Record<string, unknown>,
  key: string,
): unknown {
  if (Object.prototype.hasOwnProperty.call(properties, key)) {
    return properties[key];
  }
  const lower = key.toLowerCase();
  const actual = Object.keys(properties).find((candidate) => candidate.toLowerCase() === lower);
  return actual ? properties[actual] : undefined;
}

function serializePropertyValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (Array.isArray(value)) {
    return value.map(serializePropertyValue).join("\n");
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function comparePropertyValue(value: unknown, query: string): boolean | null {
  const match = /^(<=|>=|<|>)(.+)$/.exec(query.trim());
  if (!match) {
    return null;
  }

  const left = comparableValue(value);
  const right = comparableValue(match[2].trim());
  if (left === null || right === null) {
    return false;
  }

  switch (match[1]) {
    case "<":
      return left < right;
    case ">":
      return left > right;
    case "<=":
      return left <= right;
    case ">=":
      return left >= right;
    default:
      return false;
  }
}

function comparableValue(value: unknown): number | string | null {
  if (typeof value === "number") {
    return value;
  }
  if (value instanceof Date) {
    return value.getTime();
  }
  if (typeof value === "string") {
    const numeric = Number(value);
    if (!Number.isNaN(numeric) && value.trim() !== "") {
      return numeric;
    }
    const timestamp = Date.parse(value);
    if (!Number.isNaN(timestamp)) {
      return timestamp;
    }
    return value;
  }
  if (typeof value === "boolean") {
    return value ? 1 : 0;
  }
  return null;
}

function normalizeStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => String(item).trim()).filter(Boolean);
}

function normalizeTag(tag: string): string {
  return tag.trim().replace(/^#/, "");
}

function tagMatches(tag: string, query: string, matchCase: boolean): boolean {
  const normalizedTag = normalizeTag(tag);
  const left = matchCase ? normalizedTag : normalizedTag.toLowerCase();
  const right = matchCase ? query : query.toLowerCase();
  return left === right || left.startsWith(`${right}/`);
}

function basename(name: string): string {
  return name.replace(/\.[^.]+$/, "");
}

function lineForOffset(text: string, offset: number): number {
  return text.slice(0, offset).split(/\r?\n/).length;
}

function trimSnippet(text: string, maxLength: number): string {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(0, maxLength - 1)).trim()}...`;
}

function clampInt(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.max(min, Math.min(max, Math.trunc(value)));
}
