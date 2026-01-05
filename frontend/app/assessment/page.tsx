import Quiz from '@/components/Quiz';

export default function AssessmentPage() {
    return (
        <div className="min-h-screen bg-gray-50 py-12">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                <div className="text-center mb-10">
                    <h1 className="text-3xl font-extrabold text-gray-900">Adaptive Assessment Engine</h1>
                    <p className="mt-2 text-gray-600">Generated dynamically from trusted knowledge sources</p>
                </div>
                <Quiz />
            </div>
        </div>
    );
}
