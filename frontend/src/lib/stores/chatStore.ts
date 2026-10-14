import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Chat, ChatMessage } from '@/lib/chatApi';
import type { ChatMessageType } from '@/components/chat/ChatMessage';

const MAX_CHATS = 50;

export interface StoredChat {
  id: number;
  title: string | null;
  created_at: string;
  updated_at: string;
  is_archived: boolean;
  messages: ChatMessageType[];
}

/** Pure transform for sidebar; use with useMemo + `state.chats` — do not use as a Zustand selector (new array each call). */
export function deriveChatsForSidebar(stored: StoredChat[]): Chat[] {
  return stored
    .filter((c) => !c.is_archived)
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .map((c) => ({
      id: c.id,
      title: c.title,
      user_id: 0,
      customer_key: null,
      created_at: c.created_at,
      updated_at: c.updated_at,
      is_archived: c.is_archived,
      message_count: c.messages.length,
      messages: c.messages.map((m) => ({
        id: m.id,
        chat_id: c.id,
        role: m.role as 'user' | 'assistant' | 'system',
        content: m.content,
        created_at: m.created_at,
      })),
    }));
}

interface ChatStoreState {
  chats: StoredChat[];
  activeChatId: number | null;

  createChat: (title?: string | null) => number;
  deleteChat: (id: number) => void;
  addMessage: (chatId: number, message: ChatMessageType) => void;
  updateChatTitle: (chatId: number, title: string) => void;
  setActiveChat: (id: number | null) => void;
  getChat: (id: number) => StoredChat | undefined;
  getChatsForSidebar: () => Chat[];
}

export const useChatStore = create<ChatStoreState>()(
  persist(
    (set, get) => ({
      chats: [],
      activeChatId: null,

      createChat: (title = null) => {
        const id = Date.now();
        const now = new Date().toISOString();

        set((state) => {
          const chats = [...state.chats];

          // Cap at MAX_CHATS: remove oldest non-active chat
          if (chats.length >= MAX_CHATS) {
            const oldestIndex = chats
              .map((c, i) => ({ id: c.id, updated_at: c.updated_at, i }))
              .filter((c) => c.id !== state.activeChatId)
              .sort((a, b) => a.updated_at.localeCompare(b.updated_at))[0]?.i;
            if (oldestIndex !== undefined) {
              chats.splice(oldestIndex, 1);
            }
          }

          chats.push({
            id,
            title,
            created_at: now,
            updated_at: now,
            is_archived: false,
            messages: [],
          });

          return { chats, activeChatId: id };
        });

        return id;
      },

      deleteChat: (id) => {
        set((state) => ({
          chats: state.chats.filter((c) => c.id !== id),
          activeChatId: state.activeChatId === id ? null : state.activeChatId,
        }));
      },

      addMessage: (chatId, message) => {
        set((state) => ({
          chats: state.chats.map((c) =>
            c.id === chatId
              ? {
                  ...c,
                  updated_at: new Date().toISOString(),
                  messages: [...c.messages, message],
                }
              : c
          ),
        }));
      },

      updateChatTitle: (chatId, title) => {
        set((state) => ({
          chats: state.chats.map((c) =>
            c.id === chatId ? { ...c, title } : c
          ),
        }));
      },

      setActiveChat: (id) => {
        set({ activeChatId: id });
      },

      getChat: (id) => {
        return get().chats.find((c) => c.id === id);
      },

      getChatsForSidebar: () => deriveChatsForSidebar(get().chats),
    }),
    {
      name: 'chat-storage',
      partialize: (state) => ({
        chats: state.chats.map((chat) => ({
          ...chat,
          messages: chat.messages.map((msg) => ({
            id: msg.id,
            role: msg.role,
            content: msg.content,
            created_at: msg.created_at,
          })),
        })),
        activeChatId: state.activeChatId,
      }),
    }
  )
);
