"use client";

/*
 * Adapted from the provided LiquidMultimodalInput component. Structural
 * behaviour (auto-sizing textarea, Enter to send, Shift+Enter newline, drag
 * and drop attachments) is kept; the presentation is restyled to the AMYPO
 * design system: neutral zinc, hairline borders, no gradients or glow, the
 * accent green only on the send button. The multimodal model selector was
 * removed: AMYPO routes automatically, so the control would be a lie.
 */

import * as React from "react";
import { IconArrowUp, IconPaperclip, IconX, IconFileDescription } from "@tabler/icons-react";
import { cn } from "@/lib/utils";

export interface AskInputProps {
  placeholder?: string;
  maxHeight?: number;
  accept?: string;
  disabled?: boolean;
  onSubmit?: (value: string, files: File[]) => void;
  onChange?: (value: string) => void;
  className?: string;
}

type AttachedFile = { id: string; file: File; preview?: string };

export function AskInput({
  placeholder = "Ask about records, policies or placement eligibility…",
  maxHeight = 200,
  accept = "image/*,application/pdf,text/*",
  disabled = false,
  onSubmit,
  onChange,
  className,
}: AskInputProps) {
  const [value, setValue] = React.useState("");
  const [files, setFiles] = React.useState<AttachedFile[]>([]);
  const [dragOver, setDragOver] = React.useState(false);
  const taRef = React.useRef<HTMLTextAreaElement>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const dragCounter = React.useRef(0);

  React.useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(Math.max(ta.scrollHeight, 56), maxHeight) + "px";
  }, [value, maxHeight]);

  function addFiles(list: FileList | File[]) {
    const arr = Array.from(list).map((f) => ({
      id: crypto.randomUUID(),
      file: f,
      preview: f.type.startsWith("image/") ? URL.createObjectURL(f) : undefined,
    }));
    setFiles((prev) => [...prev, ...arr]);
  }

  function removeFile(id: string) {
    setFiles((prev) => {
      const f = prev.find((x) => x.id === id);
      if (f?.preview) URL.revokeObjectURL(f.preview);
      return prev.filter((x) => x.id !== id);
    });
  }

  function submit() {
    if (disabled || (!value.trim() && files.length === 0)) return;
    onSubmit?.(value, files.map((f) => f.file));
    setValue("");
    files.forEach((f) => f.preview && URL.revokeObjectURL(f.preview));
    setFiles([]);
    if (taRef.current) taRef.current.style.height = "56px";
  }

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div
      className={cn("w-full", className)}
      onDragEnter={(e) => {
        e.preventDefault();
        dragCounter.current++;
        if (e.dataTransfer.types.includes("Files")) setDragOver(true);
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        dragCounter.current--;
        if (dragCounter.current === 0) setDragOver(false);
      }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        dragCounter.current = 0;
        setDragOver(false);
        if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
      }}
    >
      <div
        className={cn(
          "relative flex w-full flex-col gap-2 rounded-lg border bg-card p-2 transition-colors duration-150",
          "border-[var(--border)]",
          dragOver && "border-[var(--accent)]"
        )}
      >
        {files.length > 0 && (
          <div className="flex flex-wrap gap-2 px-1 pt-1">
            {files.map((f) => (
              <div
                key={f.id}
                className="group/file relative flex shrink-0 items-center gap-2 rounded-md border bg-muted px-2 py-1.5"
              >
                <IconFileDescription size={16} className="text-muted-foreground" />
                <span className="max-w-[140px] truncate text-xs font-medium">
                  {f.file.name}
                </span>
                <button
                  type="button"
                  onClick={() => removeFile(f.id)}
                  aria-label={`Remove ${f.file.name}`}
                  className="grid h-5 w-5 place-items-center rounded-full text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-[var(--destructive)]"
                >
                  <IconX size={12} stroke={2.5} />
                </button>
              </div>
            ))}
          </div>
        )}

        <textarea
          ref={taRef}
          value={value}
          disabled={disabled}
          onChange={(e) => {
            setValue(e.target.value);
            onChange?.(e.target.value);
          }}
          onKeyDown={handleKey}
          placeholder={placeholder}
          aria-label="Chat input"
          className="w-full resize-none bg-transparent px-2 py-1.5 text-[15px] leading-relaxed text-foreground outline-none placeholder:text-muted-foreground disabled:opacity-60"
          style={{ minHeight: "56px", maxHeight }}
        />

        <div className="flex items-center gap-1 px-1 pb-0.5">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            aria-label="Attach files"
            className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground"
          >
            <IconPaperclip size={17} />
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={accept}
            hidden
            onChange={(e) => {
              if (e.target.files?.length) addFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <span className="ml-auto hidden text-xs text-muted-foreground sm:block">
            Enter to send · Shift+Enter for a new line
          </span>
          <button
            type="button"
            onClick={submit}
            disabled={disabled || (!value.trim() && files.length === 0)}
            aria-label="Send message"
            className={cn(
              "ml-1 grid h-8 w-8 shrink-0 place-items-center rounded-md transition-colors duration-150",
              "bg-[var(--accent)] text-[var(--accent-foreground)]",
              "hover:opacity-90",
              "disabled:bg-muted disabled:text-muted-foreground"
            )}
          >
            <IconArrowUp size={16} stroke={2.5} />
          </button>
        </div>

        {dragOver && (
          <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center rounded-lg bg-card/80 text-sm font-medium text-[var(--accent)]">
            Drop files here
          </div>
        )}
      </div>
    </div>
  );
}
