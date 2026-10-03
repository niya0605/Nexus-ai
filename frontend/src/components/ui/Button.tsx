import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost";
export type ButtonSize = "md" | "lg";

const base =
  "inline-flex items-center justify-center rounded-lg font-medium transition-all duration-200 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background " +
  "disabled:opacity-50 disabled:pointer-events-none disabled:translate-y-0 disabled:shadow-none";

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-accent-foreground shadow-[0_10px_35px_rgb(201_168_119/8%)] hover:-translate-y-0.5 hover:bg-accent-hover hover:shadow-[0_12px_40px_rgb(201_168_119/18%)]",
  secondary: "border border-border bg-surface text-foreground hover:border-zinc-600 hover:bg-surface-raised",
  ghost: "text-foreground hover:bg-surface",
};

const sizeClasses: Record<ButtonSize, string> = {
  md: "h-10 px-4 text-sm",
  lg: "h-12 px-6 text-base",
};

interface ButtonVariantOptions {
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
}

/**
 * Shared className builder for anything that should look like a button —
 * the `<Button>` component below, but also `<Link>`s that need identical
 * styling (e.g. landing page CTAs). Keeps the two visually identical
 * without a polymorphic/"as" component, which isn't needed at this scope.
 */
export function buttonVariants({
  variant = "primary",
  size = "md",
  className = "",
}: ButtonVariantOptions = {}): string {
  return [base, variantClasses[variant], sizeClasses[size], className].filter(Boolean).join(" ");
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function Button({ variant = "primary", size = "md", className = "", ...props }: ButtonProps) {
  return <button className={buttonVariants({ variant, size, className })} {...props} />;
}
