import type { Metadata } from "next";
import Link from "next/link";
import { AuthCard } from "@/components/auth/AuthCard";
import { LoginForm } from "@/components/auth/LoginForm";

export const metadata: Metadata = {
  title: "Login — Nexus AI",
  description: "Log in to your Nexus AI workspace.",
};

export default function LoginPage() {
  return (
    <AuthCard
      heading="Welcome back"
      subheading="Log in to your Nexus AI workspace"
      footer={
        <>
          Don&apos;t have an account?{" "}
          <Link href="/register" className="font-medium text-accent hover:text-accent-hover">
            Create one
          </Link>
        </>
      }
    >
      <LoginForm />
    </AuthCard>
  );
}
