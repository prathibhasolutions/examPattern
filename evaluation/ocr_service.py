"""
Modular OCR Service for extracting text from images.
Can be extended or replaced with different OCR providers.
"""

from abc import ABC, abstractmethod
import os
import logging
from pathlib import Path
from PIL import Image
import pytesseract

logger = logging.getLogger(__name__)


class OCRProvider(ABC):
    """Abstract base class for OCR providers."""
    
    @abstractmethod
    def extract_text(self, image_path: str) -> str:
        """
        Extract text from an image.
        
        Args:
            image_path: Full path to the image file
            
        Returns:
            Extracted text string
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this OCR provider is available/configured."""
        pass


class TesseractOCRProvider(OCRProvider):
    """OCR provider using Tesseract."""
    
    def is_available(self) -> bool:
        """Check if Tesseract is installed."""
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False
    
    def extract_text(self, image_path: str) -> str:
        """
        Extract text from image using Tesseract OCR.
        
        Args:
            image_path: Full path to the image file
            
        Returns:
            Extracted text or empty string if extraction fails
        """
        try:
            if not os.path.exists(image_path):
                logger.warning(f"Image file not found: {image_path}")
                return ""
            
            # Optimize image for OCR
            image = Image.open(image_path)
            
            # Convert to grayscale for better OCR accuracy
            if image.mode != 'L':
                image = image.convert('L')
            
            # Extract text using Tesseract
            # Config: --psm 6 = assume a single uniform block of text
            text = pytesseract.image_to_string(
                image,
                config='--psm 6'
            )
            
            logger.info(f"Successfully extracted text from {image_path}")
            return text.strip()
        
        except Exception as e:
            logger.error(f"Error extracting text from {image_path}: {str(e)}")
            return ""


class GoogleVisionOCRProvider(OCRProvider):
    """OCR provider using Google Cloud Vision API (optional)."""
    
    def __init__(self, api_key: str = None):
        """
        Initialize with Google API key.
        
        Args:
            api_key: Google Cloud Vision API key
        """
        self.api_key = api_key or os.getenv('GOOGLE_VISION_API_KEY')
    
    def is_available(self) -> bool:
        """Check if Google Vision credentials are available."""
        try:
            from google.cloud import vision
            return bool(self.api_key or os.getenv('GOOGLE_APPLICATION_CREDENTIALS'))
        except ImportError:
            return False
    
    def extract_text(self, image_path: str) -> str:
        """Extract text using Google Cloud Vision API."""
        try:
            from google.cloud import vision
            
            if not os.path.exists(image_path):
                logger.warning(f"Image file not found: {image_path}")
                return ""
            
            client = vision.ImageAnnotatorClient()
            
            with open(image_path, 'rb') as image_file:
                content = image_file.read()
            
            image = vision.Image(content=content)
            response = client.text_detection(image=image)
            
            if response.text_annotations:
                text = response.text_annotations[0].description
                logger.info(f"Successfully extracted text from {image_path} using Google Vision")
                return text.strip()
            
            return ""
        
        except Exception as e:
            logger.error(f"Google Vision OCR error for {image_path}: {str(e)}")
            return ""


class OCRService:
    """Main OCR service with provider abstraction."""
    
    def __init__(self, provider: OCRProvider = None):
        """
        Initialize OCR service with a provider.
        
        Args:
            provider: OCRProvider instance. If None, uses TesseractOCRProvider.
        """
        if provider is None:
            provider = TesseractOCRProvider()
        
        self.provider = provider
        
        if not self.provider.is_available():
            logger.warning(
                f"OCR provider {type(provider).__name__} is not available. "
                "Text extraction will be skipped."
            )
    
    def extract_text(self, image_path: str) -> str:
        """
        Extract text from an image.
        
        Args:
            image_path: Full path to the image file
            
        Returns:
            Extracted text
        """
        if not self.provider.is_available():
            return ""
        
        return self.provider.extract_text(image_path)
    
    def set_provider(self, provider: OCRProvider):
        """
        Switch to a different OCR provider.
        
        Args:
            provider: New OCRProvider instance
        """
        self.provider = provider
        logger.info(f"Switched to {type(provider).__name__} OCR provider")
    
    def is_available(self) -> bool:
        """Check if OCR is available."""
        return self.provider.is_available()


# Global OCR service instance
_ocr_service = None


def get_ocr_service() -> OCRService:
    """Get or create the global OCR service instance."""
    global _ocr_service
    if _ocr_service is None:
        _ocr_service = OCRService()
    return _ocr_service


def set_ocr_provider(provider: OCRProvider):
    """Set a custom OCR provider globally."""
    global _ocr_service
    service = get_ocr_service()
    service.set_provider(provider)
