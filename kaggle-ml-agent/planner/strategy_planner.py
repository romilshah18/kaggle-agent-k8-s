import anthropic
import os
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class StrategyPlanner:
    def __init__(self, competition_info: Dict[str, Any]):
        self.competition_info = competition_info
        self.client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        
    def create_strategy(self) -> Dict[str, Any]:
        """
        Use LLM to create competition strategy
        """
        logger.info("Creating strategy with Claude...")
        
        # Build context for LLM
        context = self._build_context()
        
        # Get strategy from Claude
        strategy = self._query_claude(context)
        
        return strategy
    
    def _build_context(self) -> str:
        """Build context string for LLM"""
        ctx = f"""
You are an expert data scientist analyzing a Kaggle competition.

Competition: {self.competition_info['name']}
Task Type: {self.competition_info['task_type']}
Evaluation Metric: {self.competition_info['metric']}

Dataset Information:
- Train shape: {self.competition_info.get('train_shape')}
- Test shape: {self.competition_info.get('test_shape')}
- Target column: {self.competition_info.get('target_column')}
- Features: {len(self.competition_info.get('feature_columns', []))} columns

Description: {self.competition_info.get('description', 'N/A')}

Create a winning strategy for this competition. Focus on:
1. What machine learning approach is best?
2. Which models should we try (limit to 2-3 fast models)?
3. What feature engineering is needed?
4. What validation strategy?

Respond in JSON format with keys: approach, models, feature_engineering, validation_strategy
Keep models simple and fast (e.g., LightGBM, XGBoost, RandomForest - no deep learning).
"""
        return ctx
    
    def _query_claude(self, context: str) -> Dict[str, Any]:
        """Query Claude for strategy"""
        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": context
                }]
            )
            
            # Parse response
            content = response.content[0].text
            
            # Try to extract JSON
            if '```json' in content:
                json_str = content.split('```json')[1].split('```')[0].strip()
            elif '```' in content:
                json_str = content.split('```')[1].split('```')[0].strip()
            else:
                json_str = content
            
            strategy = json.loads(json_str)
            logger.info("✓ Strategy created with Claude")
            
            return strategy
            
        except Exception as e:
            logger.warning(f"Claude query failed, using fallback strategy: {e}")
            return self._fallback_strategy()
    
    def _fallback_strategy(self) -> Dict[str, Any]:
        """Fallback strategy if LLM fails"""
        task_type = self.competition_info['task_type']
        
        if task_type == 'classification':
            return {
                "approach": "Gradient boosting with cross-validation",
                "models": ["LightGBM", "XGBoost"],
                "feature_engineering": "Handle missing values, encode categoricals, scale numerics",
                "validation_strategy": "5-fold stratified cross-validation"
            }
        else:  # regression
            return {
                "approach": "Ensemble of gradient boosting models",
                "models": ["LightGBM", "XGBoost"],
                "feature_engineering": "Handle missing values, encode categoricals, log-transform target if needed",
                "validation_strategy": "5-fold cross-validation"
            }

