'use client';

import { ArrowLeft } from 'lucide-react';
import { useRouter } from 'next/navigation';
import Quiz from '@/components/Quiz';
import SubjectPicker from '@/components/SubjectPicker';

export default function AssessmentPage() {
    const router = useRouter();

    return (
        <div className="min-h-screen bg-gray-50">
            {/* Header */}
            <header className="bg-white shadow-sm border-b border-gray-200">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-4">
                            <button
                                onClick={() => router.push('/')}
                                className="text-gray-600 hover:text-gray-900"
                                aria-label="Back to home"
                            >
                                <ArrowLeft className="w-6 h-6" />
                            </button>
                            <div>
                                <h1 className="text-3xl font-extrabold text-gray-900">
                                    Adaptive Assessment Engine
                                </h1>
                                <p className="mt-2 text-gray-600">
                                    Generated dynamically from trusted knowledge sources
                                </p>
                            </div>
                        </div>
                        <SubjectPicker />
                    </div>
                </div>
            </header>

            {/* Main Content */}
            <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
                <Quiz />
            </main>
        </div>
    );
}
