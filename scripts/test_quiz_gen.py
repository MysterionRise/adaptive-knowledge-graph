import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from backend.app.student.quiz_generator import QuizGenerator
from backend.app.ui_payloads.quiz import Quiz

async def main():
    print("Testing Quiz Generator...")
    try:
        # Note: This requires the DB/LLM connection to be active or mocked.
        # Since I cannot easily start the full Docker stack here, I will primarily rely on code analysis 
        # unless I can verify the services are up. 
        # However, looking at previous context, there are services potentially running?
        # The user said "No browser pages are currently open".
        
        # I'll try to instantiate the generator. If it fails connection, I'll catch it.
        generator = QuizGenerator()
        
        # We need to mock the retriever and LLM if services aren't running.
        # But for this sanity check, let's see if imports work and if we can create the object.
        print("Successfully instantiated QuizGenerator.")
        
        # Logic verification (without calling external services)
        # Verify Pydantic models
        print("Verifying Pydantic models...")
        q = Quiz(
            id="1", 
            title="Test", 
            questions=[]
        )
        print(f"Model created: {q}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
