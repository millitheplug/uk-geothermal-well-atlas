import type { Metadata } from "next";

import { SignUpScreen } from "@/components/auth/sign-up-screen";

export const metadata: Metadata = { title: "Create an account" };

export default function SignUpPage() {
  return <SignUpScreen />;
}
