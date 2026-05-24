export type SearchSort = "score" | "mtime_desc" | "mtime_asc" | "path";

export interface SearchInput {
  query: string;
  max_results?: number;
  context_chars?: number;
  sort?: SearchSort;
  debug_score_details?: boolean;
}

export interface SearchDocument {
  path: string;
  name: string;
  ext: string;
  title?: string;
  content: string;
  mtime: number;
  ctime?: number;
  tags?: string[];
  aliases?: string[];
  properties?: Record<string, unknown>;
  headings?: SearchTextPart[];
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

export interface SearchScoreDetails {
  field_score: number;
  body_score: number;
  coverage_score: number;
  phrase_score: number;
  recency_score: number;
  matched_terms: string[];
  field_breakdown: Record<string, number>;
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
  score_details?: SearchScoreDetails;
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
  scoring: ScoringContext;
}

interface EvalResult {
  ok: boolean;
  matches: SearchMatch[];
  score: number;
  matched_terms?: Set<string>;
  score_details?: MutableScoreDetails;
}

interface SearchTermInfo {
  value: string;
  key: string;
  exact: boolean;
}

interface DocumentScoreStats {
  bodyLength: number;
}

interface ScoringContext {
  documents: SearchDocument[];
  queryTerms: SearchTermInfo[];
  queryTermKeys: string[];
  termDocumentFrequency: Map<string, number>;
  documentStats: Map<SearchDocument, DocumentScoreStats>;
  avgBodyLength: number;
}

interface MutableScoreDetails {
  field_score: number;
  body_score: number;
  coverage_score: number;
  phrase_score: number;
  recency_score: number;
  field_breakdown: Record<string, number>;
  field_terms: Record<string, Set<string>>;
}

const FIELD_SCORE_WEIGHTS: Record<string, number> = {
  title: 6,
  file: 6,
  alias: 5,
  heading: 4,
  tag: 3,
  property: 3,
  path: 2,
  task: 2.5,
};
const BODY_BM25_K1 = 1.2;
const BODY_BM25_B = 0.75;
const MAX_RECENCY_SCORE = 0.5;

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
  const scoring = buildScoringContext(documents, ast);
  const matches: SearchResultItem[] = [];

  for (const doc of documents) {
    const result = evaluateNode(ast, doc, { matchCase: false, scoring });
    if (!result.ok) {
      continue;
    }

    const firstMatch = result.matches[0] ?? {
      field: "content",
      text: doc.content,
    };
    const matchedTerms = result.matched_terms ?? new Set<string>();
    const coverageScore = scoreCoverage(scoring, matchedTerms);
    const rawScore = result.score + coverageScore;
    const details = result.score_details ?? emptyScoreDetails();
    details.coverage_score += coverageScore;
    const fieldCoverageScore = scoreFieldCoverage(scoring, details);
    details.field_score += fieldCoverageScore;
    details.field_breakdown.field_coverage =
      (details.field_breakdown.field_coverage ?? 0) + fieldCoverageScore;

    matches.push({
      path: doc.path,
      ext: doc.ext,
      score: rawScore + fieldCoverageScore,
      matches: result.matches.slice(0, 8),
      snippet: makeSnippet(doc, firstMatch, contextChars),
      field: firstMatch.field,
      line: firstMatch.line,
      tags: normalizeStringList(doc.tags),
      aliases: normalizeStringList(doc.aliases),
      mtime: doc.mtime,
      truncated: result.matches.length > 8,
      score_details: input.debug_score_details
        ? finalizeScoreDetails(details, matchedTerms)
        : undefined,
    });
  }

  if (sort === "score") {
    applyRecencyScore(matches);
  }
  for (const item of matches) {
    item.score = Math.round(item.score * 100) / 100;
    if (!input.debug_score_details) {
      delete item.score_details;
    }
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
      const matchedTerms = new Set<string>();
      const details = emptyScoreDetails();
      for (const child of node.children) {
        const result = evaluateNode(child, doc, options);
        if (!result.ok) {
          return { ok: false, matches: [], score: 0 };
        }
        allMatches.push(...result.matches);
        score += result.score;
        mergeMatchedTerms(matchedTerms, result.matched_terms);
        mergeScoreDetails(details, result.score_details);
      }
      return {
        ok: true,
        matches: allMatches,
        score,
        matched_terms: matchedTerms,
        score_details: details,
      };
    }
    case "or": {
      const allMatches: SearchMatch[] = [];
      let score = 0;
      const matchedTerms = new Set<string>();
      const details = emptyScoreDetails();
      for (const child of node.children) {
        const result = evaluateNode(child, doc, options);
        if (result.ok) {
          allMatches.push(...result.matches);
          score += result.score;
          mergeMatchedTerms(matchedTerms, result.matched_terms);
          mergeScoreDetails(details, result.score_details);
        }
      }
      return {
        ok: allMatches.length > 0 || score > 0,
        matches: allMatches,
        score,
        matched_terms: matchedTerms,
        score_details: details,
      };
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
    return evaluateTextNode(child, `${doc.name}\n${basename(doc.name)}`, "file", doc, options, FIELD_SCORE_WEIGHTS.file);
  }
  if (field === "path") {
    return evaluateTextNode(child, doc.path, "path", doc, options, FIELD_SCORE_WEIGHTS.path);
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
    return evaluateParts(child, getSections(doc), "section", doc, options, FIELD_SCORE_WEIGHTS.heading);
  }
  if (field === "task") {
    return evaluateParts(child, getTasks(doc), "task", doc, options, FIELD_SCORE_WEIGHTS.task);
  }
  if (field === "task-todo") {
    return evaluateParts(
      child,
      getTasks(doc).filter((task) => task.status === "todo"),
      "task-todo",
      doc,
      options,
      FIELD_SCORE_WEIGHTS.task,
    );
  }
  if (field === "task-done") {
    return evaluateParts(
      child,
      getTasks(doc).filter((task) => task.status === "done"),
      "task-done",
      doc,
      options,
      FIELD_SCORE_WEIGHTS.task,
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
  const basenameMatches = findTermMatches(basename(doc.name), value, "file", options, exact);
  const titleMatches = findTermMatches(doc.title ?? basename(doc.name), value, "title", options, exact);
  const pathMatches = findTermMatches(doc.path, value, "path", options, exact);
  const aliasMatches = findStringListMatches(doc.aliases, value, "alias", options, exact);
  const tagMatches = findStringListMatches(doc.tags, value, "tag", options, exact);
  const propertyMatches = findTermMatches(
    serializeProperties(doc.properties ?? {}),
    value,
    "property",
    options,
    exact,
  );
  const headingMatches = findPartMatches(getHeadings(doc), value, "heading", options, exact);
  const taskMatches = findPartMatches(getTasks(doc), value, "task", options, exact);
  const candidateMatches = [...fileMatches, ...pathMatches, ...contentMatches];
  const isCandidate = candidateMatches.length > 0;
  const matches = [
    ...titleMatches,
    ...fileMatches,
    ...basenameMatches,
    ...aliasMatches,
    ...headingMatches,
    ...tagMatches,
    ...propertyMatches,
    ...pathMatches,
    ...taskMatches,
    ...contentMatches,
  ];
  const matchedTerms = matchedTermSet(options.scoring, value, exact, isCandidate);
  const fieldBreakdown: Record<string, number> = {};
  const fieldScore =
    scoreWeightedMatches(fieldBreakdown, "title", titleMatches, FIELD_SCORE_WEIGHTS.title) +
    scoreWeightedMatches(fieldBreakdown, "file", [...fileMatches, ...basenameMatches], FIELD_SCORE_WEIGHTS.file) +
    scoreWeightedMatches(fieldBreakdown, "alias", aliasMatches, FIELD_SCORE_WEIGHTS.alias) +
    scoreWeightedMatches(fieldBreakdown, "heading", headingMatches, FIELD_SCORE_WEIGHTS.heading) +
    scoreWeightedMatches(fieldBreakdown, "tag", tagMatches, FIELD_SCORE_WEIGHTS.tag) +
    scoreWeightedMatches(fieldBreakdown, "property", propertyMatches, FIELD_SCORE_WEIGHTS.property) +
    scoreWeightedMatches(fieldBreakdown, "path", pathMatches, FIELD_SCORE_WEIGHTS.path) +
    scoreWeightedMatches(fieldBreakdown, "task", taskMatches, FIELD_SCORE_WEIGHTS.task);
  const bodyScore = scoreBodyTerm(doc, value, exact, contentMatches.length, options.scoring);
  const phraseScore =
    exact && matches.length > 0
      ? scorePhrase(value, {
          titleMatches,
          fileMatches: [...fileMatches, ...basenameMatches],
          aliasMatches,
          headingMatches,
          contentMatches,
        })
      : 0;
  const details = emptyScoreDetails();
  details.field_score += fieldScore;
  details.body_score += bodyScore;
  details.phrase_score += phraseScore;
  mergeFieldBreakdown(details.field_breakdown, fieldBreakdown);
  recordFieldTerms(details, matchedTerms, {
    title: titleMatches,
    file: [...fileMatches, ...basenameMatches],
    alias: aliasMatches,
    heading: headingMatches,
    tag: tagMatches,
    property: propertyMatches,
    path: pathMatches,
    task: taskMatches,
  });

  return {
    ok: isCandidate,
    matches,
    score: fieldScore + bodyScore + phraseScore,
    matched_terms: matchedTerms,
    score_details: details,
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
  const fieldBreakdown: Record<string, number> = {};
  const fileScore = scoreWeightedMatches(fieldBreakdown, "file", fileMatches, FIELD_SCORE_WEIGHTS.file);
  const pathScore = scoreWeightedMatches(fieldBreakdown, "path", pathMatches, FIELD_SCORE_WEIGHTS.path);
  const bodyScore = Math.min(contentMatches.length, 3);
  const details = emptyScoreDetails();
  details.field_score += fileScore + pathScore;
  details.body_score += bodyScore;
  mergeFieldBreakdown(details.field_breakdown, fieldBreakdown);
  return {
    ok: matches.length > 0,
    matches,
    score: fileScore + pathScore + bodyScore,
    score_details: details,
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
    title: "",
    tags: [],
    aliases: [],
    properties: {},
    headings: [],
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
    matched_terms: result.matched_terms,
    score_details: scaleScoreDetails(result.score_details, weight),
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
  const matchedTerms = new Set<string>();
  const details = emptyScoreDetails();
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
      mergeMatchedTerms(matchedTerms, result.matched_terms);
      mergeScoreDetails(details, result.score_details);
    }
  }
  return {
    ok: matches.length > 0,
    matches,
    score,
    matched_terms: matchedTerms,
    score_details: details,
  };
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
    const details = emptyScoreDetails();
    const score = Math.min(matches.length, 3) * FIELD_SCORE_WEIGHTS.tag;
    details.field_score += score;
    details.field_breakdown.tag = score;
    return {
      ok: matches.length > 0,
      matches,
      score,
      matched_terms: matchedTermSet(options.scoring, child.value, child.exact, matches.length > 0),
      score_details: details,
    };
  }
  return evaluateTextNode(child, tags.join("\n"), "tag", doc, options, FIELD_SCORE_WEIGHTS.tag);
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
    const details = emptyScoreDetails();
    details.field_score += FIELD_SCORE_WEIGHTS.property;
    details.field_breakdown.property = FIELD_SCORE_WEIGHTS.property;
    return {
      ok: true,
      matches: [{ field: "property", text: key }],
      score: FIELD_SCORE_WEIGHTS.property,
      score_details: details,
    };
  }

  const serialized = serializePropertyValue(value);
  if (parsed.value.trim().toLowerCase() === "null") {
    const empty = serialized.trim() === "";
    const details = emptyScoreDetails();
    if (empty) {
      details.field_score += FIELD_SCORE_WEIGHTS.property;
      details.field_breakdown.property = FIELD_SCORE_WEIGHTS.property;
    }
    return {
      ok: empty,
      matches: empty ? [{ field: "property", text: `${key}: null` }] : [],
      score: empty ? FIELD_SCORE_WEIGHTS.property : 0,
      score_details: details,
    };
  }

  const comparison = comparePropertyValue(value, parsed.value);
  if (comparison !== null) {
    const details = emptyScoreDetails();
    if (comparison) {
      details.field_score += FIELD_SCORE_WEIGHTS.property;
      details.field_breakdown.property = FIELD_SCORE_WEIGHTS.property;
    }
    return {
      ok: comparison,
      matches: comparison
        ? [{ field: "property", text: `${key}: ${serialized}` }]
        : [],
      score: comparison ? FIELD_SCORE_WEIGHTS.property : 0,
      score_details: details,
    };
  }

  const node = parseSearchQuery(parsed.value);
  const result = evaluateTextNode(node, serialized, "property", doc, options, FIELD_SCORE_WEIGHTS.property);
  return result.ok
    ? {
      ok: true,
      matches: result.matches.map((match) => ({
        ...match,
        text: `${key}: ${match.text}`,
      })),
      score: result.score,
      matched_terms: result.matched_terms,
      score_details: result.score_details,
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

function findStringListMatches(
  values: unknown,
  term: string,
  field: string,
  options: EvalOptions,
  exact: boolean,
): SearchMatch[] {
  return normalizeStringList(values).flatMap((value) =>
    findTermMatches(value, term, field, options, exact),
  );
}

function findPartMatches(
  parts: SearchTextPart[],
  term: string,
  field: string,
  options: EvalOptions,
  exact: boolean,
): SearchMatch[] {
  return parts.flatMap((part) =>
    findTermMatches(part.text, term, field, options, exact).map((match) => ({
      ...match,
      line: part.line ?? match.line,
    })),
  );
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

function buildScoringContext(
  documents: SearchDocument[],
  ast: SearchNode,
): ScoringContext {
  const queryTerms = collectScoringTerms(ast);
  const queryTermKeys = Array.from(new Set(queryTerms.map((term) => term.key)));
  const documentStats = new Map<SearchDocument, DocumentScoreStats>();
  let totalBodyLength = 0;
  for (const doc of documents) {
    const bodyLength = countSearchTerms(doc.content);
    documentStats.set(doc, { bodyLength });
    totalBodyLength += bodyLength;
  }
  const avgBodyLength = documents.length > 0 ? totalBodyLength / documents.length : 1;
  const termDocumentFrequency = new Map<string, number>();
  for (const key of queryTermKeys) {
    let count = 0;
    for (const doc of documents) {
      if (countTermOccurrences(doc.content, key) > 0) {
        count += 1;
      }
    }
    termDocumentFrequency.set(key, count);
  }
  return {
    documents,
    queryTerms,
    queryTermKeys,
    termDocumentFrequency,
    documentStats,
    avgBodyLength: Math.max(1, avgBodyLength),
  };
}

function collectScoringTerms(node: SearchNode): SearchTermInfo[] {
  switch (node.type) {
    case "term": {
      const key = normalizeTermKey(node.value);
      return key ? [{ value: node.value, key, exact: node.exact }] : [];
    }
    case "and":
    case "or":
      return node.children.flatMap(collectScoringTerms);
    case "field":
      return collectScoringTerms(node.child);
    case "not":
    case "regex":
    case "property":
    case "empty":
      return [];
  }
}

function scoreCoverage(
  scoring: ScoringContext,
  matchedTerms: Set<string>,
): number {
  if (scoring.queryTermKeys.length === 0) {
    return 0;
  }
  const matchedCount = scoring.queryTermKeys.filter((key) => matchedTerms.has(key)).length;
  const ratio = matchedCount / scoring.queryTermKeys.length;
  return 4 * ratio * ratio;
}

function scoreFieldCoverage(
  scoring: ScoringContext,
  details: MutableScoreDetails,
): number {
  if (scoring.queryTermKeys.length < 2) {
    return 0;
  }
  let score = 0;
  for (const [field, terms] of Object.entries(details.field_terms)) {
    const matchedCount = scoring.queryTermKeys.filter((key) => terms.has(key)).length;
    if (matchedCount < 2) {
      continue;
    }
    const ratio = matchedCount / scoring.queryTermKeys.length;
    if (field === "title" || field === "file" || field === "alias" || field === "heading") {
      score += 10 * ratio * ratio;
    } else if (field === "tag" || field === "property" || field === "task") {
      score += 3 * ratio * ratio;
    }
  }
  return score;
}

function applyRecencyScore(results: SearchResultItem[]): void {
  if (results.length < 2) {
    return;
  }
  const mtimes = results.map((item) => item.mtime).filter(Number.isFinite);
  if (mtimes.length < 2) {
    return;
  }
  const min = Math.min(...mtimes);
  const max = Math.max(...mtimes);
  const spread = max - min;
  if (spread <= 0) {
    return;
  }
  for (const item of results) {
    const recencyScore = ((item.mtime - min) / spread) * MAX_RECENCY_SCORE;
    item.score += recencyScore;
    if (item.score_details) {
      item.score_details.recency_score =
        Math.round((item.score_details.recency_score + recencyScore) * 100) / 100;
    }
  }
}

function scoreBodyTerm(
  doc: SearchDocument,
  value: string,
  exact: boolean,
  matchCount: number,
  scoring: ScoringContext,
): number {
  if (matchCount <= 0) {
    return 0;
  }
  const key = normalizeTermKey(value);
  if (!key) {
    return 0;
  }
  const stats = scoring.documentStats.get(doc);
  const bodyLength = Math.max(1, stats?.bodyLength ?? countSearchTerms(doc.content));
  const df = scoring.termDocumentFrequency.get(key) ?? 0;
  const totalDocs = Math.max(1, scoring.documents.length);
  const idf = Math.log(1 + (totalDocs - df + 0.5) / (df + 0.5));
  const tf = exact ? 1 : Math.min(matchCount, 8);
  const normalized =
    (tf * (BODY_BM25_K1 + 1)) /
    (tf + BODY_BM25_K1 * (1 - BODY_BM25_B + BODY_BM25_B * (bodyLength / scoring.avgBodyLength)));
  return normalized * Math.max(0.2, idf);
}

function scoreWeightedMatches(
  breakdown: Record<string, number>,
  field: string,
  matches: SearchMatch[],
  weight: number,
): number {
  if (matches.length === 0) {
    return 0;
  }
  const score = weight;
  breakdown[field] = (breakdown[field] ?? 0) + score;
  return score;
}

function recordFieldTerms(
  details: MutableScoreDetails,
  matchedTerms: Set<string>,
  fields: Record<string, SearchMatch[]>,
): void {
  for (const [field, matches] of Object.entries(fields)) {
    if (matches.length === 0) {
      continue;
    }
    const terms = details.field_terms[field] ?? new Set<string>();
    for (const term of matchedTerms) {
      terms.add(term);
    }
    details.field_terms[field] = terms;
  }
}

function scorePhrase(
  _value: string,
  matches: {
    titleMatches: SearchMatch[];
    fileMatches: SearchMatch[];
    aliasMatches: SearchMatch[];
    headingMatches: SearchMatch[];
    contentMatches: SearchMatch[];
  },
): number {
  if (
    matches.titleMatches.length > 0 ||
    matches.fileMatches.length > 0 ||
    matches.aliasMatches.length > 0 ||
    matches.headingMatches.length > 0
  ) {
    return 4;
  }
  if (matches.contentMatches.length > 0) {
    return 2;
  }
  return 0;
}

function matchedTermSet(
  scoring: ScoringContext,
  value: string,
  _exact: boolean,
  matched: boolean,
): Set<string> {
  if (!matched) {
    return new Set();
  }
  const key = normalizeTermKey(value);
  if (!key || !scoring.queryTermKeys.includes(key)) {
    return new Set();
  }
  return new Set([key]);
}

function countSearchTerms(text: string): number {
  const matches = text.match(/[\p{L}\p{N}_-]+/gu);
  return Math.max(1, matches?.length ?? 0);
}

function countTermOccurrences(text: string, normalizedTerm: string): number {
  if (!normalizedTerm) {
    return 0;
  }
  const haystack = text.toLowerCase();
  let count = 0;
  let start = haystack.indexOf(normalizedTerm);
  while (start !== -1 && count < 100) {
    count += 1;
    start = haystack.indexOf(normalizedTerm, start + Math.max(1, normalizedTerm.length));
  }
  return count;
}

function normalizeTermKey(value: string): string {
  return value.trim().toLowerCase();
}

function serializeProperties(properties: Record<string, unknown>): string {
  return Object.entries(properties)
    .map(([key, value]) => `${key}: ${serializePropertyValue(value)}`)
    .join("\n");
}

function emptyScoreDetails(): MutableScoreDetails {
  return {
    field_score: 0,
    body_score: 0,
    coverage_score: 0,
    phrase_score: 0,
    recency_score: 0,
    field_breakdown: {},
    field_terms: {},
  };
}

function mergeMatchedTerms(target: Set<string>, source: Set<string> | undefined): void {
  if (!source) {
    return;
  }
  for (const term of source) {
    target.add(term);
  }
}

function mergeScoreDetails(
  target: MutableScoreDetails,
  source: MutableScoreDetails | undefined,
): void {
  if (!source) {
    return;
  }
  target.field_score += source.field_score;
  target.body_score += source.body_score;
  target.coverage_score += source.coverage_score;
  target.phrase_score += source.phrase_score;
  target.recency_score += source.recency_score;
  mergeFieldBreakdown(target.field_breakdown, source.field_breakdown);
  for (const [field, terms] of Object.entries(source.field_terms)) {
    const targetTerms = target.field_terms[field] ?? new Set<string>();
    for (const term of terms) {
      targetTerms.add(term);
    }
    target.field_terms[field] = targetTerms;
  }
}

function mergeFieldBreakdown(
  target: Record<string, number>,
  source: Record<string, number>,
): void {
  for (const [field, score] of Object.entries(source)) {
    target[field] = (target[field] ?? 0) + score;
  }
}

function scaleScoreDetails(
  details: MutableScoreDetails | undefined,
  factor: number,
): MutableScoreDetails | undefined {
  if (!details) {
    return undefined;
  }
  const scaled = emptyScoreDetails();
  scaled.field_score = details.field_score * factor;
  scaled.body_score = details.body_score * factor;
  scaled.coverage_score = details.coverage_score * factor;
  scaled.phrase_score = details.phrase_score * factor;
  scaled.recency_score = details.recency_score * factor;
  for (const [field, score] of Object.entries(details.field_breakdown)) {
    scaled.field_breakdown[field] = score * factor;
  }
  for (const [field, terms] of Object.entries(details.field_terms)) {
    scaled.field_terms[field] = new Set(terms);
  }
  return scaled;
}

function finalizeScoreDetails(
  details: MutableScoreDetails,
  matchedTerms: Set<string>,
): SearchScoreDetails {
  const roundedBreakdown: Record<string, number> = {};
  for (const [field, score] of Object.entries(details.field_breakdown)) {
    roundedBreakdown[field] = Math.round(score * 100) / 100;
  }
  return {
    field_score: Math.round(details.field_score * 100) / 100,
    body_score: Math.round(details.body_score * 100) / 100,
    coverage_score: Math.round(details.coverage_score * 100) / 100,
    phrase_score: Math.round(details.phrase_score * 100) / 100,
    recency_score: Math.round(details.recency_score * 100) / 100,
    matched_terms: Array.from(matchedTerms).sort(),
    field_breakdown: roundedBreakdown,
  };
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

function getHeadings(doc: SearchDocument): SearchTextPart[] {
  if (doc.headings?.length) {
    return doc.headings;
  }
  const headings: SearchTextPart[] = [];
  for (const section of getSections(doc)) {
    const match = /^(#{1,6})\s+(.+)$/m.exec(section.text);
    if (match) {
      headings.push({
        text: match[2].trim(),
        line: section.line,
      });
    }
  }
  return headings;
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
