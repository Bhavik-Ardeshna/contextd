/**
 * Chat API Client for Conversational Intelligence.
 * 
 * Provides functions for managing chat conversations and
 * streaming AI-generated insights from the knowledge graph.
 */

import { apiClient } from './api';

// ============================================================================
// Types
// ============================================================================

export interface Chat {
  id: number;
  title: string | null;
  user_id: number;
  customer_key: string | null;
  created_at: string;
  updated_at: string;
  is_archived: boolean;
  message_count: number;
  messages?: ChatMessage[];
}

export interface ChatReference {
  type: string;
  id: string | number;
  name: string;
  nav_path: string;
}

export interface ChatMessage {
  id: number;
  chat_id: number;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
  model_used?: string;
  tokens_used?: number;
  completion_tokens?: number;
  prompt_tokens?: number;
  context_id?: number;
  context?: ChatContext;
  references?: ChatReference[];
}

export interface ChatContext {
  id: number;
  query_text: string;
  query_classification?: QueryClassification;
  nodes_count?: number;
  edges_count?: number;
  search_results_count?: number;
  created_at: string;
  // Full data (only included when requested)
  search_results_json?: string;
  subgraph_json?: string;
  llm_context_text?: string;
}

export interface QueryClassification {
  intent: string;
  confidence: number;
  entities?: Array<{
    type: string;
    value: string;
  }>;
  suggested_view?: string;
}

export interface SendMessageResponse {
  user_message: ChatMessage;
  assistant_message: ChatMessage;
  context_summary: string;
}

export interface StreamChunk {
  type: 'user_message' | 'context' | 'chunk' | 'done' | 'error';
  data: string | ChatMessage;
}

export interface ListChatsResponse {
  conversations: Chat[];
  total: number;
  limit: number;
  offset: number;
}

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Format chat title for display
 */
export function formatChatTitle(chat: Chat): string {
  if (chat.title) {
    return chat.title;
  }
  if (chat.messages && chat.messages.length > 0) {
    const firstMessage = chat.messages.find(m => m.role === 'user');
    if (firstMessage) {
      return firstMessage.content.slice(0, 50) + (firstMessage.content.length > 50 ? '...' : '');
    }
  }
  return 'New Conversation';
}

/**
 * Group chats by date
 */
export function groupChatsByDate(chats: Chat[]): {
  today: Chat[];
  yesterday: Chat[];
  thisWeek: Chat[];
  older: Chat[];
} {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const thisWeek = new Date(today);
  thisWeek.setDate(thisWeek.getDate() - 7);

  const grouped = {
    today: [] as Chat[],
    yesterday: [] as Chat[],
    thisWeek: [] as Chat[],
    older: [] as Chat[],
  };

  chats.forEach(chat => {
    const chatDate = new Date(chat.updated_at);
    if (chatDate >= today) {
      grouped.today.push(chat);
    } else if (chatDate >= yesterday) {
      grouped.yesterday.push(chat);
    } else if (chatDate >= thisWeek) {
      grouped.thisWeek.push(chat);
    } else {
      grouped.older.push(chat);
    }
  });

  return grouped;
}

// ============================================================================
// Chat CRUD Functions
// ============================================================================

/**
 * List all conversations for the current user.
 */
export async function listChats(
  limit: number = 50,
  offset: number = 0
): Promise<Chat[]> {
  try {
    const response = await apiClient.get(`/chat/conversations?limit=${limit}&offset=${offset}`);
    if (response.ok && response.data) {
      return response.data.conversations || response.data || [];
    }
    return [];
  } catch (error) {
    console.error('Failed to list chats:', error);
    return [];
  }
}

/**
 * Get a single chat by ID.
 */
export async function getChat(id: number): Promise<Chat> {
  const response = await apiClient.get(`/chat/conversations/${id}`);
  if (!response.ok || !response.data) {
    throw new Error('Failed to load chat');
  }
  return response.data;
}

/**
 * Create a new chat.
 */
export async function createChat(data: { title?: string; customer_key?: string }): Promise<Chat> {
  const response = await apiClient.post('/chat/conversations', data);
  if (!response.ok || !response.data) {
    throw new Error('Failed to create chat');
  }
  return response.data;
}

/**
 * Update a chat.
 */
export async function updateChat(id: number, data: { title?: string }): Promise<Chat> {
  const response = await apiClient.patch(`/chat/conversations/${id}`, data);
  if (!response.ok || !response.data) {
    throw new Error('Failed to update chat');
  }
  return response.data;
}

/**
 * Delete a chat.
 */
export async function deleteChat(id: number): Promise<void> {
  const response = await apiClient.delete(`/chat/conversations/${id}`);
  if (!response.ok) {
    throw new Error('Failed to delete chat');
  }
}

/**
 * Get message context.
 */
export async function getMessageContext(chatId: number, messageId: number): Promise<ChatContext | null> {
  try {
    const response = await apiClient.get(`/chat/conversations/${chatId}/messages/${messageId}/context`);
    if (response.ok && response.data) {
      return response.data;
    }
    return null;
  } catch (error) {
    console.error('Failed to get message context:', error);
    return null;
  }
}

// ============================================================================
// Streaming Functions
// ============================================================================

export interface StreamCallbacks {
  onUserMessage?: (message: ChatMessage) => void;
  onContext?: (summary: string) => void;
  onChunk?: (text: string) => void;
  onDone?: (message: ChatMessage) => void;
  onError?: (error: string) => void;
}

/**
 * Stream a message response.
 */
export function streamMessage(
  chatId: number,
  query: string,
  mode: string = 'default',
  callbacks: StreamCallbacks = {}
): { abort: () => void } {
  const abortController = new AbortController();
  let userMessage: ChatMessage | null = null;

  // Start streaming
  (async () => {
    try {
      const response = await apiClient.post(
        `/chat/conversations/${chatId}/messages/stream`,
        { content: query, prompt_type: mode },
        { 
          signal: abortController.signal,
          extraHeaders: {
            'Accept': 'text/event-stream',
          }
        }
      );

      if (!response.ok || !response.body) {
        throw new Error('Stream failed');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (data === '[DONE]') {
              return;
            }

            try {
              const parsed = JSON.parse(data);
              
              if (parsed.type === 'user_message') {
                userMessage = parsed.data;
                callbacks.onUserMessage?.(userMessage);
              } else if (parsed.type === 'context') {
                callbacks.onContext?.(parsed.data);
              } else if (parsed.type === 'chunk') {
                callbacks.onChunk?.(parsed.data);
              } else if (parsed.type === 'done') {
                callbacks.onDone?.(parsed.data);
                return;
              } else if (parsed.type === 'error') {
                throw new Error(parsed.data);
              }
            } catch (e) {
              // Skip invalid JSON
            }
          }
        }
      }
    } catch (error: any) {
      if (error.name === 'AbortError') {
        return;
      }
      callbacks.onError?.(error.message || 'Stream error');
    }
  })();

  return {
    abort: () => {
      abortController.abort();
    },
  };
}
