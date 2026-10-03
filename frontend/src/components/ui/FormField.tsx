import type { InputHTMLAttributes } from "react";
import { Input } from "@/components/ui/Input";

interface FormFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  id: string;
}

/** Label + input pair, consistently styled — shared by every auth form. */
export function FormField({ label, id, ...inputProps }: FormFieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-foreground">
        {label}
      </label>
      <Input id={id} name={id} {...inputProps} />
    </div>
  );
}
