"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { FormField } from "@/components/ui/FormField";

export function RegisterForm() {
  const [submitted, setSubmitted] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Not yet connected to the backend. The real endpoint,
    // `POST /api/v1/auth/register`, already exists (Sprint 1B) and
    // returns the created user in `pending_verification` status — this
    // form just isn't wired up to call it yet. No request is sent.
    setSubmitted(true);
  }

  return (
    <div className="flex flex-col gap-4">
      {submitted && (
        <div
          role="status"
          className="rounded-lg border border-accent/30 bg-accent/10 px-3 py-2.5 text-sm text-foreground"
        >
          Account creation isn&apos;t connected yet — this form previews the upcoming sign-up flow.
        </div>
      )}

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <FormField label="Full name" id="display_name" type="text" autoComplete="name" required maxLength={100} />
        <FormField label="Email" id="email" type="email" autoComplete="email" required />
        <FormField
          label="Password"
          id="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={8}
          maxLength={128}
        />
        <Button type="submit" className="mt-2 w-full">
          Create account
        </Button>
      </form>
    </div>
  );
}
