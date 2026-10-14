import React, { useState, useRef, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { apiClient, API_CONFIG } from '@/lib/api';
import { Copy, Check, Braces, TerminalSquare, Clock, Terminal, Code, Layers } from 'lucide-react';
import { useTheme } from '@/lib/theme-provider';
import { cn } from '@/lib/utils';
import { PrismAsyncLight as SyntaxHighlighter } from 'react-syntax-highlighter';
import materialOceanic from 'react-syntax-highlighter/dist/esm/styles/prism/material-oceanic';
import oneLight from 'react-syntax-highlighter/dist/esm/styles/prism/one-light';
import { PythonIcon } from '@/components/icons/PythonIcon';
import { NodeIcon } from '@/components/icons/NodeIcon';
import { McpIcon } from '@/components/icons/McpIcon';
import { ClaudeIcon } from '@/components/icons/ClaudeIcon';
import { CursorIcon } from '@/components/icons/CursorIcon';
import { WindsurfIcon } from '@/components/icons/WindsurfIcon';
import { CodeBlock } from '@/components/ui/code-block';

interface QueryToolAndLiveDocProps {
    collectionReadableId: string;
}

export const QueryToolAndLiveDoc = ({ collectionReadableId }: QueryToolAndLiveDocProps) => {
    // QueryTool state
    const [query, setQuery] = useState('');
    const [objects, setObjects] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [statusCode, setStatusCode] = useState<number | null>(null);
    const [responseTime, setResponseTime] = useState<number | null>(null);
    const [searchStatus, setSearchStatus] = useState<string | null>(null);
    const [copied, setCopied] = useState(false);

    // LiveApiDoc state
    const [viewMode, setViewMode] = useState<"restapi" | "mcpserver">("mcpserver");
    const [apiTab, setApiTab] = useState<"rest" | "python" | "node" | "claude" | "cursor" | "windsurf" | "server">("claude");
    const [apiKey, setApiKey] = useState<string>("YOUR_API_KEY");

    const { resolvedTheme } = useTheme();
    const responseRef = useRef<HTMLDivElement>(null);
    const isDark = resolvedTheme === 'dark';

    // Get API key from session storage
    useEffect(() => {
        const sessionApiKey = sessionStorage.getItem('semantic_mcp_api_key');
        if (sessionApiKey) {
            setApiKey(sessionApiKey);
        } else {
            setApiKey("YOUR_API_KEY");
        }
    }, []);

    // Reset tab when switching view modes to avoid invalid states
    const handleViewModeChange = (mode: "restapi" | "mcpserver") => {
        setViewMode(mode);
        if (mode === "restapi") {
            setApiTab("rest");
        } else {
            setApiTab("claude");
        }
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();

        // Don't proceed if query is empty
        if (!query.trim()) return;

        setIsLoading(true);
        setStatusCode(null);
        setResponseTime(null);
        setSearchStatus(null);
        const startTime = performance.now();

        try {
            const response = await apiClient.post(
                `/collections/${collectionReadableId}/graph-search`,
                { query, include_edges: true, search_limit: 10, max_depth: 2 }
            );
            const endTime = performance.now();
            setResponseTime(Math.round(endTime - startTime));
            setStatusCode(response.status);

            if (!response.ok) {
                throw new Error(`Search failed: ${response.statusText}`);
            }

            const data = await response.json();

            setSearchStatus(data.stats ? 'success' : null);
            setObjects(JSON.stringify(data, null, 2));
        } catch (error) {
            console.error('Error searching:', error);
            setSearchStatus('error');
            setObjects(JSON.stringify(
                { error: error instanceof Error ? error.message : String(error) },
                null,
                2,
            ));
        } finally {
            setIsLoading(false);
        }
    };

    const handleCopyObjects = async () => {
        try {
            await navigator.clipboard.writeText(objects);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch (error) {
            console.error('Failed to copy:', error);
        }
    };

    // Format API URL for display
    const getApiUrl = () => {
        // Extract base URL domain for display, removing protocol
        const baseUrlDomain = API_CONFIG.baseURL.replace(/^https?:\/\//, '');
        const baseUrl = `${baseUrlDomain}/collections/${collectionReadableId || '{collection_id}'}/graph-search`;
        return baseUrl;
    };

    // Function to build API examples for documentation
    const getApiEndpoints = () => {
        const apiBaseUrl = API_CONFIG.baseURL;
        const apiUrl = `${apiBaseUrl}/collections/${collectionReadableId}/graph-search`;
        const exampleQuery = query || "...";
        const requestBody = JSON.stringify(
            { query: exampleQuery, include_edges: true, search_limit: 10, max_depth: 2 },
            null,
            2,
        );

        // Create the cURL command
        const curlSnippet = `curl -X 'POST' \\
  '${apiUrl}' \\
  -H 'accept: application/json' \\
  -H 'x-api-key: ${apiKey}' \\
  -H 'Content-Type: application/json' \\
  -d '${requestBody}'`;

        // Create the Python code
        const pythonSnippet =
            `from contextd import ContextDSDK

client = ContextDSDK(
    api_key="${apiKey}",
)
client.collections.graph_search(
    readable_id="${collectionReadableId}",
    query="${exampleQuery}",
    include_edges=True,
    search_limit=10,
    max_depth=2,
)`;

        // Create the Node.js code
        const nodeSnippet =
            `import { ContextDSDKClient } from "@contextd/sdk";

const client = new ContextDSDKClient({ apiKey: "${apiKey}" });
await client.collections.graphSearch("${collectionReadableId}", {
    query: "${exampleQuery}",
    includeEdges: true,
    searchLimit: 10,
    maxDepth: 2
});`;

        // MCP Server code examples
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

        const installSnippet =
            `# Install the MCP server globally
npm install -g contextd-mcp-search@1.0.7

# Or run directly with npx
npx contextd-mcp-search`;

        const cliSnippet =
            `# Set environment variables
export CONTEXTD_API_KEY="${apiKey}"
export CONTEXTD_COLLECTION="${collectionReadableId}"
export CONTEXTD_BASE_URL="${API_CONFIG.baseURL}"

# Run the MCP server
contextd-mcp-search`;

        return {
            curlSnippet,
            pythonSnippet,
            nodeSnippet,
            configSnippet,
            installSnippet,
            cliSnippet
        };
    };

    // JSON syntax highlighting styles
    const syntaxStyle = isDark ? materialOceanic : oneLight;

    // Create a custom style that maintains text coloring but fits our design
    const customSyntaxStyle = {
        ...syntaxStyle,
        'pre[class*="language-"]': {
            ...syntaxStyle['pre[class*="language-"]'],
            background: 'transparent',
            margin: 0,
            padding: 0,
        },
        'code[class*="language-"]': {
            ...syntaxStyle['code[class*="language-"]'],
            background: 'transparent',
        }
    };

    // Get status indicator colors
    const getStatusIndicator = (status: string | null) => {
        if (!status) return "bg-gray-400";

        switch (status) {
            case 'success':
                return isDark ? "bg-green-400" : "bg-green-500";
            case 'no_relevant_results':
                return isDark ? "bg-amber-400" : "bg-amber-500";
            default:
                return isDark ? "bg-red-400" : "bg-red-500";
        }
    };

    const docLinkFooter = (
        <div className="text-xs flex items-center gap-2">
            <span className={isDark ? "text-gray-400" : "text-gray-500"}>→</span>
            <a
                href="https://docs.contextd.local/api-concepts"
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
    );

    const mcpConfigFooter = (
        <div className="text-xs flex items-center gap-2">
            <span className={isDark ? "text-gray-400" : "text-gray-500"}>→</span>
            <span className={isDark ? "text-gray-400" : "text-gray-500"}>
                Add this to your MCP client configuration file (usually{" "}
                {apiTab === "claude" && "~/.config/Claude/claude_desktop_config.json for Claude"}
                {apiTab === "cursor" && "~/.cursor/mcp.json for Cursor"}
                {apiTab === "windsurf" && "~/.windsurf/mcp.json for Windsurf"}
            </span>
        </div>
    );

    const mcpInstallFooter = (
        <div className="text-xs flex items-center gap-2">
            <span className={isDark ? "text-gray-400" : "text-gray-500"}>→</span>
            <span className={isDark ? "text-gray-400" : "text-gray-500"}>
                After installation, configure your MCP client with the environment variables shown above
            </span>
        </div>
    );

    return (
        <div className="w-full mb-6">
            {/* QUERY TOOL SECTION */}
            <div className="mb-6">
                {/* API Endpoint display */}
                <div className="mb-2">
                    <div className="flex h-8 items-stretch rounded-md border overflow-hidden shadow-xs">
                        <div className={cn(
                            "flex items-center justify-center min-w-[48px]",
                            isDark ? "bg-emerald-900/40 text-emerald-300" : "bg-emerald-50 text-emerald-500"
                        )}>
                            <span className="text-xs font-semibold">POST</span>
                        </div>
                        <div className={cn(
                            "flex-grow flex items-center px-3 py-1.5 text-xs font-mono min-w-0",
                            isDark
                                ? "bg-gray-900 text-gray-300"
                                : "bg-gray-50/80 text-gray-700"
                        )}>
                            <span className="opacity-75 truncate">{getApiUrl()}</span>
                        </div>
                        <div className="border-l flex items-center">
                            <Button
                                variant="ghost"
                                size="icon"
                                className={cn(
                                    "h-8 w-8 rounded-none",
                                    isDark ? "text-gray-400 hover:text-gray-300" : "text-gray-500 hover:text-gray-700"
                                )}
                                onClick={() => navigator.clipboard.writeText(`https://${getApiUrl()}`)}
                            >
                                <Copy className="h-3.5 w-3.5" />
                            </Button>
                        </div>
                    </div>
                </div>

                {/* Query input */}
                <div className="mb-0">
                    <form onSubmit={handleSubmit} className="flex items-stretch">
                        {/* Query input field */}
                        <div className="flex flex-1 h-9 rounded-l-md border-y border-l overflow-hidden">
                            <div className={cn(
                                "flex items-center justify-center min-w-[70px] border-r",
                                isDark
                                    ? "bg-gray-800/80 text-gray-300 border-gray-700"
                                    : "bg-gray-50/80 text-gray-600 border-gray-200"
                            )}>
                                <span className="text-xs font-medium">query=</span>
                            </div>
                            <input
                                type="text"
                                placeholder="..."
                                value={query}
                                onChange={(e) => setQuery(e.target.value)}
                                className={cn(
                                    "w-full px-3 h-full text-sm",
                                    isDark
                                        ? "bg-gray-900 text-gray-200"
                                        : "bg-white/90"
                                )}
                                style={{ outline: 'none', border: 'none' }}
                            />
                        </div>

                        {/* Search button */}
                        <Button
                            type="submit"
                            disabled={isLoading || !query.trim()}
                            className={cn(
                                "rounded-l-none rounded-r-md h-9 px-5",
                                isDark
                                    ? query.trim() ? "bg-blue-600 hover:bg-blue-700" : "bg-blue-600/90 hover:bg-blue-600/60"
                                    : query.trim() ? "bg-blue-500 hover:bg-blue-600" : "bg-blue-500/90 hover:bg-blue-500/60"
                            )}
                        >
                            {isLoading ? 'Searching...' : 'Search'}
                        </Button>
                    </form>
                </div>

                {/* Unified Response Section */}
                <div ref={responseRef} className={cn(
                    "mt-8 rounded-lg shadow-sm overflow-hidden",
                    (!objects && !isLoading) ? "hidden" : "",
                    isDark ? "bg-gray-950" : "bg-white",
                    isDark ? "ring-1 ring-gray-800" : "ring-1 ring-gray-200"
                )}>
                    {/* Status Ribbon - Always visible */}
                    {isLoading ? (
                        <div className="h-1.5 w-full relative overflow-hidden">
                            <div className={cn(
                                "absolute inset-0 h-1.5 bg-gradient-to-r from-blue-500 to-indigo-500"
                            )}></div>
                            <div className={cn(
                                "absolute inset-0 h-1.5 bg-gradient-to-r from-transparent via-white to-transparent",
                                "animate-shimmer"
                            )}
                                style={{
                                    backgroundSize: '200% 100%',
                                    animationDuration: '1.5s',
                                    animationIterationCount: 'infinite',
                                    animationTimingFunction: 'linear'
                                }}
                            ></div>
                        </div>
                    ) : (
                        <div className={cn(
                            "h-1.5 w-full bg-gradient-to-r",
                            searchStatus === 'success'
                                ? "from-green-500 to-emerald-500"
                                : searchStatus === 'no_relevant_results'
                                    ? "from-amber-400 to-amber-500"
                                    : "from-gray-400 to-gray-500"
                        )}></div>
                    )}

                    {/* Simplified Metadata Bar */}
                    <div className={cn(
                        "w-full py-2 px-3",
                        isDark ? "bg-gray-900/60" : "bg-gray-50/80",
                        "flex items-center justify-between"
                    )}>
                        <div className="flex items-center gap-3">
                            <div className="flex items-center">
                                <Layers className="h-3.5 w-3.5 mr-2 opacity-70" />
                                <span className="text-xs font-medium">Response Metadata</span>
                            </div>

                            {searchStatus && (
                                <div className="flex items-center">
                                    <div className={cn(
                                        "h-1.5 w-1.5 rounded-full mr-1.5",
                                        getStatusIndicator(searchStatus)
                                    )}></div>
                                    <span className="text-xs opacity-80">
                                        {searchStatus.replace(/_/g, ' ')}
                                    </span>
                                </div>
                            )}
                        </div>

                        <div className="flex items-center gap-3">
                            {statusCode && (
                                <div className="flex items-center text-xs opacity-80">
                                    <TerminalSquare className="h-3.5 w-3.5 mr-1.5" />
                                    <span className="font-mono">HTTP {statusCode}</span>
                                </div>
                            )}

                            {responseTime && (
                                <div className="flex items-center text-xs opacity-80">
                                    <Clock className="h-3.5 w-3.5 mr-1.5" />
                                    <span className="font-mono">{responseTime}ms</span>
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Content Section */}
                    <div className="flex flex-col">
                        {/* JSON Response Section */}
                        {objects || isLoading ? (
                            <div className={cn(
                                "border-t",
                                isDark ? "border-gray-800/50" : "border-gray-200/50"
                            )}>
                                <div className={cn(
                                    "flex items-center justify-between p-3 border-b bg-gradient-to-r",
                                    isDark
                                        ? "from-gray-800/90 to-gray-900/70 border-gray-700/50 text-gray-300"
                                        : "from-gray-50 to-gray-100/70 border-gray-200/70 text-gray-700"
                                )}>
                                    <div className="flex items-center">
                                        <Braces className="h-3.5 w-3.5 mr-2 opacity-80" />
                                        <span className="text-xs font-semibold">JSON RESPONSE</span>
                                    </div>
                                    {!isLoading && objects && (
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            className="text-xs gap-1 h-6"
                                            onClick={handleCopyObjects}
                                        >
                                            {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                                            Copy
                                        </Button>
                                    )}
                                </div>
                                <div className={cn(
                                    "overflow-auto max-h-[400px] bg-gradient-to-b",
                                    isDark ? "from-gray-900/80 to-gray-900/60" : "from-white to-gray-50/80"
                                )}>
                                    {isLoading ? (
                                        <div className="p-4 animate-pulse space-y-2">
                                            <div className="flex gap-2">
                                                <div className="h-4 w-4 bg-gray-200 dark:bg-gray-700 rounded"></div>
                                                <div className="h-4 w-24 bg-gray-200 dark:bg-gray-700 rounded"></div>
                                            </div>
                                            <div className="flex gap-2 ml-4">
                                                <div className="h-4 w-16 bg-gray-200 dark:bg-gray-700 rounded"></div>
                                                <div className="h-4 w-32 bg-gray-200 dark:bg-gray-700 rounded"></div>
                                            </div>
                                            <div className="flex gap-2 ml-4">
                                                <div className="h-4 w-20 bg-gray-200 dark:bg-gray-700 rounded"></div>
                                                <div className="h-4 w-24 bg-gray-200 dark:bg-gray-700 rounded"></div>
                                            </div>
                                            <div className="flex gap-2 ml-4">
                                                <div className="h-4 w-12 bg-gray-200 dark:bg-gray-700 rounded"></div>
                                                <div className="h-4 w-36 bg-gray-200 dark:bg-gray-700 rounded"></div>
                                            </div>
                                            <div className="h-4 w-8 bg-gray-200 dark:bg-gray-700 rounded"></div>
                                        </div>
                                    ) : (
                                        <SyntaxHighlighter
                                            language="json"
                                            style={customSyntaxStyle}
                                            customStyle={{
                                                fontSize: '0.8rem',
                                                background: 'transparent',
                                                padding: '1rem',
                                                margin: 0
                                            }}
                                            showLineNumbers={true}
                                        >
                                            {objects}
                                        </SyntaxHighlighter>
                                    )}
                                </div>
                            </div>
                        ) : null}
                    </div>
                </div>
            </div>

            {/* LIVE API DOC SECTION */}
            <div className="mb-2 mt-2">
                <div className="flex w-full flex-col md:flex-row gap-4 opacity-95">
                    {/* Left section with view mode buttons */}
                    <div className="w-full md:w-1/4 flex flex-row md:flex-col gap-3">
                        {/* MCP Server button - now first and default */}
                        <Button
                            variant="outline"
                            onClick={() => handleViewModeChange("mcpserver")}
                            className={cn(
                                "w-full justify-start p-4 rounded-md text-sm flex items-center gap-3 transition-all",
                                "border-input bg-background text-muted-foreground hover:text-foreground hover:bg-accent/10 dark:border-border dark:bg-card dark:hover:bg-muted",
                                viewMode === "mcpserver" && "border-primary bg-primary/5 dark:bg-primary/10 text-primary dark:text-primary-foreground font-medium"
                            )}
                        >
                            <McpIcon className={cn(
                                "h-5 w-5",
                                viewMode === "mcpserver" ? "text-primary" : "text-muted-foreground"
                            )} />
                            <span>MCP Server</span>
                        </Button>

                        <Button
                            variant="outline"
                            onClick={() => handleViewModeChange("restapi")}
                            className={cn(
                                "w-full justify-start p-4 rounded-md text-sm flex items-center gap-3 transition-all",
                                "border-input bg-background text-muted-foreground hover:text-foreground hover:bg-accent/10 dark:border-border dark:bg-card dark:hover:bg-muted",
                                viewMode === "restapi" && "border-primary bg-primary/5 dark:bg-primary/10 text-primary dark:text-primary-foreground font-medium"
                            )}
                        >
                            <Code className={cn(
                                "h-5 w-5",
                                viewMode === "restapi" ? "text-primary" : "text-muted-foreground"
                            )} />
                            <span>RestAPI</span>
                        </Button>
                    </div>

                    {/* Right content area */}
                    <div className="w-full md:w-3/4">
                        <div className={cn(
                            "rounded-lg overflow-hidden border",
                            isDark ? "bg-gray-900 border-gray-800" : "bg-gray-100 border-gray-200"
                        )}>
                            {/* Tabs - Different tabs based on view mode */}
                            <div className="flex space-x-1 p-2 w-fit overflow-x-auto border-b border-b-gray-200 dark:border-b-gray-800">
                                {viewMode === "restapi" ? (
                                    <>
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => setApiTab("rest")}
                                            className={cn(
                                                "rounded-md text-sm flex items-center gap-2",
                                                isDark
                                                    ? "text-gray-200 hover:bg-gray-800/80"
                                                    : "text-gray-700 hover:bg-gray-200/80",
                                                apiTab === "rest"
                                                    ? isDark ? "bg-gray-800" : "bg-gray-200"
                                                    : ""
                                            )}
                                        >
                                            <Terminal className="h-5 w-5" />
                                            <span>cURL</span>
                                        </Button>
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => setApiTab("python")}
                                            className={cn(
                                                "rounded-md text-sm flex items-center gap-2",
                                                isDark
                                                    ? "text-gray-200 hover:bg-gray-800/80"
                                                    : "text-gray-700 hover:bg-gray-200/80",
                                                apiTab === "python"
                                                    ? isDark ? "bg-gray-800" : "bg-gray-200"
                                                    : ""
                                            )}
                                        >
                                            <PythonIcon className="h-5 w-5" />
                                            <span>Python</span>
                                        </Button>
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => setApiTab("node")}
                                            className={cn(
                                                "rounded-md text-sm flex items-center gap-2",
                                                isDark
                                                    ? "text-gray-200 hover:bg-gray-800/80"
                                                    : "text-gray-700 hover:bg-gray-200/80",
                                                apiTab === "node"
                                                    ? isDark ? "bg-gray-800" : "bg-gray-200"
                                                    : ""
                                            )}
                                        >
                                            <NodeIcon className="h-5 w-5" />
                                            <span>Node.js</span>
                                        </Button>
                                    </>
                                ) : (
                                    <>
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => setApiTab("claude")}
                                            className={cn(
                                                "rounded-md text-sm flex items-center gap-2",
                                                isDark
                                                    ? "text-gray-200 hover:bg-gray-800/80"
                                                    : "text-gray-700 hover:bg-gray-200/80",
                                                apiTab === "claude"
                                                    ? isDark ? "bg-gray-800" : "bg-gray-200"
                                                    : ""
                                            )}
                                        >
                                            <ClaudeIcon className="h-6 w-6" />
                                            <span>Claude</span>
                                        </Button>
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => setApiTab("cursor")}
                                            className={cn(
                                                "rounded-md text-sm flex items-center gap-2",
                                                isDark
                                                    ? "text-gray-200 hover:bg-gray-800/80"
                                                    : "text-gray-700 hover:bg-gray-200/80",
                                                apiTab === "cursor"
                                                    ? isDark ? "bg-gray-800" : "bg-gray-200"
                                                    : ""
                                            )}
                                        >
                                            <CursorIcon className="h-6 w-6" />
                                            <span>Cursor</span>
                                        </Button>
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => setApiTab("windsurf")}
                                            className={cn(
                                                "rounded-md text-sm flex items-center gap-2",
                                                isDark
                                                    ? "text-gray-200 hover:bg-gray-800/80"
                                                    : "text-gray-700 hover:bg-gray-200/80",
                                                apiTab === "windsurf"
                                                    ? isDark ? "bg-gray-800" : "bg-gray-200"
                                                    : ""
                                            )}
                                        >
                                            <WindsurfIcon className="h-6 w-6" />
                                            <span>Windsurf</span>
                                        </Button>
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => setApiTab("server")}
                                            className={cn(
                                                "rounded-md text-sm flex items-center gap-2",
                                                isDark
                                                    ? "text-gray-200 hover:bg-gray-800/80"
                                                    : "text-gray-700 hover:bg-gray-200/80",
                                                apiTab === "server"
                                                    ? isDark ? "bg-gray-800" : "bg-gray-200"
                                                    : ""
                                            )}
                                        >
                                            <McpIcon className="h-5 w-5" />
                                            <span>Server/Other</span>
                                        </Button>
                                    </>
                                )}
                            </div>

                            {/* Tab Content */}
                            <div className="h-[330px]">
                                {viewMode === "restapi" && (
                                    <>
                                        {apiTab === "rest" && (
                                            <CodeBlock
                                                code={getApiEndpoints().curlSnippet}
                                                language="bash"
                                                badgeText="POST"
                                                badgeColor="bg-emerald-600 hover:bg-emerald-600"
                                                title={`/collections/${collectionReadableId}/graph-search`}
                                                footerContent={docLinkFooter}
                                                height="100%"
                                                className="h-full rounded-none border-none"
                                            />
                                        )}

                                        {apiTab === "python" && (
                                            <CodeBlock
                                                code={getApiEndpoints().pythonSnippet}
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
                                                code={getApiEndpoints().nodeSnippet}
                                                language="javascript"
                                                badgeText="SDK"
                                                badgeColor="bg-blue-600 hover:bg-blue-600"
                                                title="ContextDSDKClient"
                                                footerContent={docLinkFooter}
                                                height="100%"
                                                className="h-full rounded-none border-none"
                                            />
                                        )}
                                    </>
                                )}

                                {viewMode === "mcpserver" && (
                                    <>
                                        {apiTab === "claude" && (
                                            <CodeBlock
                                                code={getApiEndpoints().configSnippet}
                                                language="json"
                                                badgeText="CONFIG"
                                                badgeColor="bg-purple-600 hover:bg-purple-600"
                                                title="Claude Desktop MCP Configuration"
                                                footerContent={mcpConfigFooter}
                                                height="100%"
                                                className="h-full rounded-none border-none"
                                            />
                                        )}

                                        {apiTab === "cursor" && (
                                            <CodeBlock
                                                code={getApiEndpoints().configSnippet}
                                                language="json"
                                                badgeText="CONFIG"
                                                badgeColor="bg-blue-600 hover:bg-blue-600"
                                                title="Cursor MCP Configuration"
                                                footerContent={mcpConfigFooter}
                                                height="100%"
                                                className="h-full rounded-none border-none"
                                            />
                                        )}

                                        {apiTab === "windsurf" && (
                                            <CodeBlock
                                                code={getApiEndpoints().configSnippet}
                                                language="json"
                                                badgeText="CONFIG"
                                                badgeColor="bg-teal-600 hover:bg-teal-600"
                                                title="Windsurf MCP Configuration"
                                                footerContent={mcpConfigFooter}
                                                height="100%"
                                                className="h-full rounded-none border-none"
                                            />
                                        )}

                                        {apiTab === "server" && (
                                            <CodeBlock
                                                code={getApiEndpoints().installSnippet}
                                                language="bash"
                                                badgeText="INSTALL"
                                                badgeColor="bg-gray-600 hover:bg-gray-600"
                                                title="Install MCP Server"
                                                footerContent={mcpInstallFooter}
                                                height="100%"
                                                className="h-full rounded-none border-none"
                                            />
                                        )}
                                    </>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
