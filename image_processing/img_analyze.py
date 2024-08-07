import base64
import io
import os
import discord
import openai
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))


async def get_base64_image(attachment: discord.Attachment) -> str:
    """Get the base64 encoded image."""
    with io.BytesIO() as image_buffer:
        await attachment.save(image_buffer)
        image_buffer.seek(0)
        return base64.b64encode(image_buffer.getvalue()).decode("utf-8")


async def analyze_image(message: discord.Message, base64_image: str) -> bool:
    """Analyze the image for payment confirmation."""
    try:
        response = openai_client.chat.completions.create(
            model='gpt-4o',
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": [
                    {"type": "text",
                     "text": "Analyze this image and determine if it shows a successful payment confirmation. The "
                             "image should be contained - order ID, product, quantity, and price. "
                             "ID, quantity, product and price)"},
                    {"type": "text", "text": message.content},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                ]}
            ],
            temperature=0.0,
        )
        response_content = response.choices[0].message.content.lower()
        print(f"OpenAI response: {response_content}")

        if "successful payment" in response_content or "payment was successful" in response_content:
            return True
        return False
    except openai.OpenAIError as e:
        print(f"OpenAI API error: {e}")
        return False
