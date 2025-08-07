import logging
import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from .models import ForwardingRule, GmailAccount, OutlookAccount

logger = logging.getLogger(__name__)

class ForwardingRuleEngine:
    """Engine for evaluating forwarding rules and determining email routing"""
    
    def __init__(self):
        self.operators = {
            'equals': self._equals,
            'contains': self._contains,
            'starts_with': self._starts_with,
            'ends_with': self._ends_with,
            'regex': self._regex,
            'in_list': self._in_list,
            'greater_than': self._greater_than,
            'less_than': self._less_than,
            'date_after': self._date_after,
            'date_before': self._date_before
        }
    
    def evaluate_rules(self, outlook_account: OutlookAccount, email_data: Dict) -> Optional[Tuple[ForwardingRule, GmailAccount]]:
        """
        Evaluate all rules for an Outlook account and return the matching rule and target Gmail account
        
        Args:
            outlook_account: The Outlook account
            email_data: Dictionary containing email metadata
            
        Returns:
            Tuple of (ForwardingRule, GmailAccount) if match found, None otherwise
        """
        try:
            # Get active rules for this Outlook account, ordered by priority
            rules = ForwardingRule.query.filter_by(
                outlook_account_id=outlook_account.id,
                is_active=True
            ).order_by(ForwardingRule.priority.asc()).all()
            
            if not rules:
                logger.debug(f"No active rules found for {outlook_account.email}")
                return None
            
            # Evaluate each rule
            for rule in rules:
                if self._evaluate_rule(rule, email_data):
                    # Get the target Gmail account
                    gmail_account = GmailAccount.query.filter_by(
                        id=rule.gmail_account_id,
                        is_active=True
                    ).first()
                    
                    if gmail_account:
                        logger.info(f"Email matched rule '{rule.rule_name}' -> {gmail_account.email}")
                        return rule, gmail_account
                    else:
                        logger.warning(f"Rule '{rule.rule_name}' points to inactive Gmail account")
                        continue
            
            logger.debug(f"No matching rules found for email: {email_data.get('subject', 'No Subject')}")
            return None
            
        except Exception as e:
            logger.error(f"Error evaluating rules: {str(e)}")
            return None
    
    def _evaluate_rule(self, rule: ForwardingRule, email_data: Dict) -> bool:
        """Evaluate a single rule against email data"""
        try:
            if not rule.filter_criteria:
                # Rule with no criteria matches all emails
                return True
            
            criteria = rule.filter_criteria
            
            # Handle AND logic (all conditions must be true)
            if 'and' in criteria:
                return all(self._evaluate_condition(cond, email_data) for cond in criteria['and'])
            
            # Handle OR logic (at least one condition must be true)
            elif 'or' in criteria:
                return any(self._evaluate_condition(cond, email_data) for cond in criteria['or'])
            
            # Single condition
            else:
                return self._evaluate_condition(criteria, email_data)
                
        except Exception as e:
            logger.error(f"Error evaluating rule '{rule.rule_name}': {str(e)}")
            return False
    
    def _evaluate_condition(self, condition: Dict, email_data: Dict) -> bool:
        """Evaluate a single condition"""
        try:
            field = condition.get('field')
            operator = condition.get('operator', 'equals')
            value = condition.get('value')
            
            if not field or value is None:
                return False
            
            # Get email field value
            email_value = self._get_email_field_value(field, email_data)
            if email_value is None:
                return False
            
            # Apply operator
            op_func = self.operators.get(operator)
            if not op_func:
                logger.warning(f"Unknown operator: {operator}")
                return False
            
            return op_func(email_value, value)
            
        except Exception as e:
            logger.error(f"Error evaluating condition: {str(e)}")
            return False
    
    def _get_email_field_value(self, field: str, email_data: Dict):
        """Extract field value from email data"""
        field_mapping = {
            'subject': lambda data: data.get('subject', ''),
            'sender': lambda data: data.get('from', {}).get('emailAddress', {}).get('address', ''),
            'sender_name': lambda data: data.get('from', {}).get('emailAddress', {}).get('name', ''),
            'sender_domain': lambda data: self._extract_domain(data.get('from', {}).get('emailAddress', {}).get('address', '')),
            'body': lambda data: data.get('body', {}).get('content', ''),
            'has_attachments': lambda data: data.get('hasAttachments', False),
            'importance': lambda data: data.get('importance', 'normal'),
            'received_date': lambda data: data.get('receivedDateTime', ''),
            'category': lambda data: ', '.join(data.get('categories', [])),
            'to_recipients': lambda data: ', '.join([r.get('emailAddress', {}).get('address', '') for r in data.get('toRecipients', [])]),
            'cc_recipients': lambda data: ', '.join([r.get('emailAddress', {}).get('address', '') for r in data.get('ccRecipients', [])]),
            'size': lambda data: data.get('bodyPreview', '')  # Approximate size
        }
        
        extractor = field_mapping.get(field)
        if extractor:
            return extractor(email_data)
        else:
            # Direct field access
            return email_data.get(field)
    
    def _extract_domain(self, email_address: str) -> str:
        """Extract domain from email address"""
        if '@' in email_address:
            return email_address.split('@')[1].lower()
        return ''
    
    # Operator implementations
    def _equals(self, email_value, condition_value) -> bool:
        """Exact match (case insensitive)"""
        return str(email_value).lower() == str(condition_value).lower()
    
    def _contains(self, email_value, condition_value) -> bool:
        """Contains substring (case insensitive)"""
        return str(condition_value).lower() in str(email_value).lower()
    
    def _starts_with(self, email_value, condition_value) -> bool:
        """Starts with (case insensitive)"""
        return str(email_value).lower().startswith(str(condition_value).lower())
    
    def _ends_with(self, email_value, condition_value) -> bool:
        """Ends with (case insensitive)"""
        return str(email_value).lower().endswith(str(condition_value).lower())
    
    def _regex(self, email_value, condition_value) -> bool:
        """Regular expression match"""
        try:
            pattern = re.compile(str(condition_value), re.IGNORECASE)
            return bool(pattern.search(str(email_value)))
        except re.error:
            logger.warning(f"Invalid regex pattern: {condition_value}")
            return False
    
    def _in_list(self, email_value, condition_value) -> bool:
        """Check if value is in a list"""
        if isinstance(condition_value, list):
            return str(email_value).lower() in [str(v).lower() for v in condition_value]
        else:
            # Treat as comma-separated string
            values = [v.strip().lower() for v in str(condition_value).split(',')]
            return str(email_value).lower() in values
    
    def _greater_than(self, email_value, condition_value) -> bool:
        """Numeric greater than"""
        try:
            return float(email_value) > float(condition_value)
        except (ValueError, TypeError):
            return False
    
    def _less_than(self, email_value, condition_value) -> bool:
        """Numeric less than"""
        try:
            return float(email_value) < float(condition_value)
        except (ValueError, TypeError):
            return False
    
    def _date_after(self, email_value, condition_value) -> bool:
        """Date after comparison"""
        try:
            # Parse email date (ISO format from Graph API)
            email_date = datetime.fromisoformat(str(email_value).replace('Z', '+00:00'))
            condition_date = datetime.fromisoformat(str(condition_value).replace('Z', '+00:00'))
            return email_date > condition_date
        except (ValueError, TypeError):
            return False
    
    def _date_before(self, email_value, condition_value) -> bool:
        """Date before comparison"""
        try:
            email_date = datetime.fromisoformat(str(email_value).replace('Z', '+00:00'))
            condition_date = datetime.fromisoformat(str(condition_value).replace('Z', '+00:00'))
            return email_date < condition_date
        except (ValueError, TypeError):
            return False
    
    def create_default_rule(self, outlook_account: OutlookAccount, gmail_account: GmailAccount) -> ForwardingRule:
        """Create a default rule that forwards all emails"""
        rule = ForwardingRule(
            outlook_account_id=outlook_account.id,
            gmail_account_id=gmail_account.id,
            rule_name=f"Default rule for {outlook_account.email}",
            description="Forward all emails (default rule)",
            filter_criteria=None,  # No criteria = match all
            priority=999,  # Low priority
            is_active=True,
            forward_attachments=True
        )
        return rule
    
    def validate_rule_criteria(self, criteria: Dict) -> Tuple[bool, str]:
        """Validate rule criteria structure"""
        try:
            if not criteria:
                return True, "Valid (matches all emails)"
            
            # Check for valid structure
            if 'and' in criteria:
                if not isinstance(criteria['and'], list):
                    return False, "'and' must be a list of conditions"
                for condition in criteria['and']:
                    valid, msg = self._validate_condition(condition)
                    if not valid:
                        return False, f"Invalid condition in 'and': {msg}"
            
            elif 'or' in criteria:
                if not isinstance(criteria['or'], list):
                    return False, "'or' must be a list of conditions"
                for condition in criteria['or']:
                    valid, msg = self._validate_condition(condition)
                    if not valid:
                        return False, f"Invalid condition in 'or': {msg}"
            
            else:
                # Single condition
                return self._validate_condition(criteria)
            
            return True, "Valid criteria"
            
        except Exception as e:
            return False, f"Validation error: {str(e)}"
    
    def _validate_condition(self, condition: Dict) -> Tuple[bool, str]:
        """Validate a single condition"""
        if not isinstance(condition, dict):
            return False, "Condition must be a dictionary"
        
        if 'field' not in condition:
            return False, "Condition must have 'field'"
        
        if 'value' not in condition:
            return False, "Condition must have 'value'"
        
        operator = condition.get('operator', 'equals')
        if operator not in self.operators:
            return False, f"Unknown operator: {operator}"
        
        return True, "Valid condition"