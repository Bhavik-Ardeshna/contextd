import React, { useState, useEffect, useMemo } from 'react';
import { Button } from '@/components/ui/button';
import { apiClient, API_CONFIG } from '@/lib/api';
import { Terminal } from 'lucide-react';
import { useTheme } from '@/lib/theme-provider';
import { cn } from '@/lib/utils';
import { PythonIcon } from '@/components/icons/PythonIcon';
import { NodeIcon } from '@/components/icons/NodeIcon';
import { McpIcon } from '@/components/icons/McpIcon';

import { CodeBlock } from '@/components/ui/code-block';
import { DESIGN_SYSTEM } from '@/lib/design-system';

interface SearchConfig {
    retrieval_strategy: "hybrid" | "neural" | "keyword";
    expand_query: boolean;
    interpret_filters: boolean;
    temporal_relevance: number;
    rerank: boolean;
    generate_answer: boolean;
    filter?: any;
}

interface ApiIntegrationDocProps {
    collectionReadableId: string;
    query?: string;
    searchConfig?: SearchConfig;
    filter?: string | null;
    apiKey?: string;
}

export const ApiIntegrationDoc = ({ collectionReadableId, query, searchConfig, filter, apiKey = "YOUR_API_KEY" }: ApiIntegrationDocProps) => {
    // LiveApiDoc state
    const [apiTab, setApiTab] = useState<"rest" | "python" | "node" | "mcp">("rest");

    const { resolvedTheme } = useTheme();
    const isDark = resolvedTheme === 'dark';



    // Memoize API endpoints to prevent expensive recalculation on every render
    const apiEndpoints = useMemo(() => {
        const apiBaseUrl = API_CONFIG.baseURL;
        const apiUrl = `${apiBaseUrl}/collections/${collectionReadableId}/graph-search`;
        const searchQuery = query || "Ask a question about your data";

        // Escape query for different contexts
        const escapeForJson = (str: string) => str.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
        const escapeForPython = (str: string) => str.replace(/\\/g, '\\\\').replace(/"/g, '\\"');

        // Parse filter if provided
        let parsedFilter = null;
        if (filter) {
            try {
                parsedFilter = JSON.parse(filter);
            } catch {
                parsedFilter = null;
            }
        }

        // Build request body with ALL parameters in specific order (new schema)
        const requestBody: any = {
            query: searchQuery,  // Will be escaped when stringified
            retrieval_strategy: searchConfig?.retrieval_strategy || "hybrid",
            expand_query: searchConfig?.expand_query ?? true,
            ...(parsedFilter ? { filter: parsedFilter } : {}),  // Include filter only if valid
            interpret_filters: searchConfig?.interpret_filters || false,
            temporal_relevance: searchConfig?.temporal_relevance ?? 0.3,
            rerank: searchConfig?.rerank ?? true,
            generate_answer: searchConfig?.generate_answer ?? false,
            limit: 20,
            offset: 0
        };

        // Create the cURL command with formatted JSON
        const jsonBody = JSON.stringify(requestBody, null, 2)
            .split('\n')
            .map((line, index, array) => {
                if (index === 0) return line;
                if (index === array.length - 1) return '  ' + line;
                return '  ' + line;
            })
            .join('\n');

        // Add note about query interpretation if enabled
        const interpretNote = searchConfig?.interpret_filters
            ? `# Note: interpret_filters is enabled, which may automatically add\n# additional filters extracted from your natural language query.\n# The filter shown below is your manual filter only.\n\n`
            : '';

        const curlSnippet = `${interpretNote}curl -X 'POST' \\
  '${apiUrl}' \\
  -H 'accept: application/json' \\
  -H 'x-api-key: ${apiKey}' \\
  -H 'Content-Type: application/json' \\
  -d '${jsonBody}'`;

        // Create the Python code with ALL parameters in specific order
        const pythonFilterStr = parsedFilter ?
            JSON.stringify(parsedFilter, null, 4)
                .split('\n')
                .map((line, index) => index === 0 ? line : '        ' + line)
                .join('\n') :
            null;

        const pythonRequestParams = [
            `        query="${escapeForPython(searchQuery)}"`,
            `        retrieval_strategy=RetrievalStrategy.${(searchConfig?.retrieval_strategy || "hybrid").toUpperCase()}`,
            `        expand_query=${(searchConfig?.expand_query ?? true) ? "True" : "False"}`,
            ...(pythonFilterStr ? [`        filter=${pythonFilterStr}`] : []),
            `        interpret_filters=${searchConfig?.interpret_filters ? "True" : "False"}`,
            `        temporal_relevance=${searchConfig?.temporal_relevance ?? 0}`,
            `        rerank=${(searchConfig?.rerank ?? true) ? "True" : "False"}`,
            `        generate_answer=${searchConfig?.generate_answer ? "True" : "False"}`,
            `        limit=1000`,
            `        offset=0`
        ];

        const pythonInterpretNote = searchConfig?.interpret_filters
            ? `# Note: interpret_filters is enabled, which may automatically add
# additional filters extracted from your natural language query.
# The filter shown below is your manual filter only.

`
            : '';

        const pythonSnippet =
            `${pythonInterpretNote}from contextd import ContextDSDK, SearchRequest, RetrievalStrategy

client = ContextDSDK(
    api_key="${apiKey}",
)

result = client.collections.search(
    readable_id="${collectionReadableId}",
    request=SearchRequest(
${pythonRequestParams.join(',\n')}
    ),
)

print(result.completion)  # AI-generated answer (if generate_answer=True)
print(len(result.results))  # Number of results`;

        // Create the Node.js code with ALL parameters in specific order
        const nodeFilterStr = parsedFilter ?
            JSON.stringify(parsedFilter, null, 4)
                .split('\n')
                .map((line, index) => index === 0 ? line : '            ' + line)
                .join('\n') :
            null;

        const nodeRequestParams = [
            `            query: "${escapeForJson(searchQuery)}"`,
            `            retrievalStrategy: "${searchConfig?.retrieval_strategy || "hybrid"}"`,
            `            expandQuery: ${searchConfig?.expand_query ?? true}`,
            ...(nodeFilterStr ? [`            filter: ${nodeFilterStr}`] : []),
            `            interpretFilters: ${searchConfig?.interpret_filters || false}`,
            `            temporalRelevance: ${searchConfig?.temporal_relevance ?? 0}`,
            `            rerank: ${searchConfig?.rerank ?? true}`,
            `            generateAnswer: ${searchConfig?.generate_answer ?? false}`,
            `            limit: 1000`,
            `            offset: 0`
        ];

        const nodeInterpretNote = searchConfig?.interpret_filters
            ? `// Note: interpretFilters is enabled, which may automatically add
// additional filters extracted from your natural language query.
// The filter shown below is your manual filter only.

`
            : '';

        const nodeSnippet =
            `${nodeInterpretNote}import { ContextDSDKClient } from "@contextd/sdk";

const client = new ContextDSDKClient({ apiKey: "${apiKey}" });

const result = await client.collections.search("${collectionReadableId}", {
    request: {
${nodeRequestParams.join(',\n')}
    }
});

console.log(result.completion);  // AI-generated answer (if generateAnswer=true)
console.log(result.results.length);  // Number of results`;

        // MCP Server code examples
        // Note: MCP servers typically don't support all advanced search parameters directly,
        // but the config is provided for basic integration
        const configSnippet =
            `{
  "mcpServers": {
    "contextd-${collectionReadableId}": {
      "command": "npx",
      "args": ["contextd-mcp-search"],
      "env": {
        "CONTEXTD_API_KEY": "${apiKey}",
        "CONTEXTD_COLLECTION": "${collectionReadableId}",
        "CONTEXTD_BASE_URL": "${API_CONFIG.baseURL}"
      }
    }
  }
}`;



        return {
            curlSnippet,
            pythonSnippet,
            nodeSnippet,
            configSnippet
        };
    }, [collectionReadableId, apiKey, searchConfig, query, filter]);



    // Memoize footer components
    const docLinkFooter = useMemo(() => (
        <div className="text-xs flex items-center gap-2">
            <span className={isDark ? "text-gray-400" : "text-gray-500"}>→</span>
            <a
                href="https://docs.contextd.local/api-reference/collections/search-advanced-collections-readable-id-search-post"
                target="_blank"
                rel="noopener noreferrer"
                className={cn(
                    "hover:underline transition-all",
                    isDark ? "text-blue-400 hover:text-blue-300" : "text-blue-600 hover:text-blue-700"
                )}
            >
                Explore the full API documentation
            </a>
        </div>
    ), [isDark]);

    const mcpConfigFooter = useMemo(() => (
        <div className="text-xs flex items-center gap-2">
            <span className={isDark ? "text-gray-400" : "text-gray-500"}>→</span>
            <span className={isDark ? "text-gray-400" : "text-gray-500"}>
                Add this to your MCP client configuration file (e.g., ~/.config/Claude/claude_desktop_config.json)
            </span>
        </div>
    ), [isDark]);

    return (
        <div className="w-full mb-6">
            {/* LIVE API DOC SECTION */}
            <div className="mb-8">
                <div className="w-full opacity-95">
                    <div className={cn(
                        DESIGN_SYSTEM.radius.card,
                        "overflow-hidden border",
                        isDark ? "bg-gray-900 border-gray-800" : "bg-gray-100 border-gray-200"
                    )}>
                        {/* Tabs */}
                        <div className="flex space-x-1 p-2 w-fit overflow-x-auto border-b border-b-gray-200 dark:border-b-gray-800">
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => setApiTab("rest")}
                                className={cn(
                                    DESIGN_SYSTEM.radius.button,
                                    DESIGN_SYSTEM.typography.sizes.header,
                                    "flex items-center",
                                    DESIGN_SYSTEM.spacing.gaps.standard,
                                    isDark
                                        ? "text-gray-200 hover:bg-gray-800/80"
                                        : "text-gray-700 hover:bg-gray-200/80",
                                    apiTab === "rest"
                                        ? isDark ? "bg-gray-800" : "bg-gray-200"
                                        : ""
                                )}
                            >
                                <Terminal className={DESIGN_SYSTEM.icons.large} />
                                <span>cURL</span>
                            </Button>
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => setApiTab("python")}
                                className={cn(
                                    DESIGN_SYSTEM.radius.button,
                                    DESIGN_SYSTEM.typography.sizes.header,
                                    "flex items-center",
                                    DESIGN_SYSTEM.spacing.gaps.standard,
                                    isDark
                                        ? "text-gray-200 hover:bg-gray-800/80"
                                        : "text-gray-700 hover:bg-gray-200/80",
                                    apiTab === "python"
                                        ? isDark ? "bg-gray-800" : "bg-gray-200"
                                        : ""
                                )}
                            >
                                <PythonIcon className={DESIGN_SYSTEM.icons.large} />
                                <span>Python</span>
                            </Button>
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => setApiTab("node")}
                                className={cn(
                                    DESIGN_SYSTEM.radius.button,
                                    DESIGN_SYSTEM.typography.sizes.header,
                                    "flex items-center",
                                    DESIGN_SYSTEM.spacing.gaps.standard,
                                    isDark
                                        ? "text-gray-200 hover:bg-gray-800/80"
                                        : "text-gray-700 hover:bg-gray-200/80",
                                    apiTab === "node"
                                        ? isDark ? "bg-gray-800" : "bg-gray-200"
                                        : ""
                                )}
                            >
                                <NodeIcon className={DESIGN_SYSTEM.icons.large} />
                                <span>Node.js</span>
                            </Button>
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => setApiTab("mcp")}
                                className={cn(
                                    DESIGN_SYSTEM.radius.button,
                                    DESIGN_SYSTEM.typography.sizes.header,
                                    "flex items-center",
                                    DESIGN_SYSTEM.spacing.gaps.standard,
                                    isDark
                                        ? "text-gray-200 hover:bg-gray-800/80"
                                        : "text-gray-700 hover:bg-gray-200/80",
                                    apiTab === "mcp"
                                        ? isDark ? "bg-gray-800" : "bg-gray-200"
                                        : ""
                                )}
                            >
                                <McpIcon className={DESIGN_SYSTEM.icons.large} />
                                <span>MCP</span>
                            </Button>
                        </div>

                        {/* Tab Content */}
                        <div className={"h-[460px]"}>
                            {apiTab === "rest" && (
                                <CodeBlock
                                    code={apiEndpoints.curlSnippet}
                                    language="bash"
                                    badgeText="POST"
                                    badgeColor="bg-amber-600 hover:bg-amber-600"
                                    title={`/collections/${collectionReadableId}/graph-search`}
                                    footerContent={docLinkFooter}
                                    height="100%"
                                    className="h-full rounded-none border-none"
                                />
                            )}

                            {apiTab === "python" && (
                                <CodeBlock
                                    code={apiEndpoints.pythonSnippet}
                                    language="python"
                                    badgeText="SDK"
                                    badgeColor="bg-blue-600 hover:bg-blue-600"
                                    title="ContextDSDK"
                                    footerContent={docLinkFooter}
                                    height="100%"
                                    className="h-full rounded-none border-none"
                                />
                            )}

                            {apiTab === "node" && (
                                <CodeBlock
                                    code={apiEndpoints.nodeSnippet}
                                    language="javascript"
                                    badgeText="SDK"
                                    badgeColor="bg-blue-600 hover:bg-blue-600"
                                    title="ContextDSDKClient"
                                    footerContent={docLinkFooter}
                                    height="100%"
                                    className="h-full rounded-none border-none"
                                />
                            )}

                            {apiTab === "mcp" && (
                                <CodeBlock
                                    code={apiEndpoints.configSnippet}
                                    language="json"
                                    badgeText="CONFIG"
                                    badgeColor="bg-purple-600 hover:bg-purple-600"
                                    title="MCP Configuration"
                                    footerContent={mcpConfigFooter}
                                    height="100%"
                                    className="h-full rounded-none border-none"
                                />
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
