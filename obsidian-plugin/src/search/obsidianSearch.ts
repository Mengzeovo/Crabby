import type { App } from "obsidian";

import { SearchDocument, SearchInput, SearchResponse, searchDocuments } from "./searchEngine";
import {
  buildDocumentForFile,
  getSearchableFiles,
} from "./searchDocumentBuilder";
import type { SearchIndex } from "./searchIndex";

export async function performObsidianSearch(
  app: App,
  input: SearchInput,
  index?: SearchIndex | null,
): Promise<SearchResponse> {
  const documents = index?.isReady()
    ? index.getDocuments()
    : await buildSearchDocuments(app);
  return searchDocuments(documents, input);
}

export async function buildSearchDocuments(app: App): Promise<SearchDocument[]> {
  const files = getSearchableFiles(app);
  const documents: SearchDocument[] = [];
  for (const file of files) {
    const document = await buildDocumentForFile(app, file);
    if (document) {
      documents.push(document);
    }
  }
  return documents;
}
