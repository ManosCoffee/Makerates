from datetime import datetime, timezone
from typing import Optional, Dict, List
from utils.helpers import load_config
from utils.dynamodb import DynamoDBClient
from utils.logging_config import root_logger as logger

CONFIG_FILE = "apis.yaml"

class QuotaManager:
    """Manages API quotas with automatic failover."""

    def __init__(self, table_name: str = "api_quota_tracker", endpoint_url: Optional[str] = None):
        self.dynamodb = DynamoDBClient(table_name, endpoint_url)
        self.apis_config = load_config(CONFIG_FILE)
        self.api_priority = sorted(
            self.apis_config.keys(),
            key=lambda k: self.apis_config[k]["priority"]
        )
        #list(self.apis_config.keys())

    def _get_active_cycle(self, api_source: str) -> Optional[Dict]:
        """
        Find the active quota cycle (30-day window).
        Returns the item if a valid cycle exists, else None.
        """
        # Query for latest item (Sort Key DESC)
        response = self.dynamodb.query(
            key_condition_expression="api_source = :api",
            expression_values={":api": api_source},
            limit=1,
            scan_index_forward=False
        )
        items = response if response else [] # DynamoDBClient.query returns list
        
        if not items:
            return None
            
        latest_item = items[0]
        # Check validity: Is NOW < TTL?
        # Requirement: "INCREMENT ... if curr date < ttl"
        ttl = float(latest_item.get("ttl", 0))
        now_ts = datetime.now(timezone.utc).timestamp()
        
        if now_ts < ttl:
            return latest_item
        else:
            logger.info(f"Cycle for {api_source} expired (TTL: {ttl} < Now: {now_ts})")
            return None

    def get_all_api_statuses(self) -> Dict[str, bool]:
        """
        Returns a dictionary of API statuses (available/unavailable) for all configured APIs.
        Used by the Kestra pipeline to determine which extractors can run.
        """
        stats = self.get_usage_stats()
        status_map = {}
        
        # Default fail-open for configured APIs if not in stats (though get_usage_stats inits them)
        for api in self.apis_config.keys():
            status_map[api] = True

        for s in stats:
            api_name = s['api_source']
            is_active = s.get('status') == 'active'
            has_quota = s.get('remaining', 0) > 0
            
            # API is available if active AND has quota
            status_map[api_name] = is_active and has_quota
            
        return status_map

    def record_request(self, api_source: str, success: bool = True, date: Optional[str] = None) -> bool:
        """
        Increment request count only if valid active cycle exists.
        If expired, create NEW cycle.
        """
        # 1. Find Active Cycle
        active_item = self._get_active_cycle(api_source)
        
        cycle_date = None
        if active_item:
            cycle_date = active_item["tracking_date"]
        else:
            # Create NEW cycle
            logger.info(f"Starting NEW monthly cycle for {api_source}")
            cycle_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            self._initialize_new_cycle(api_source, start_date=cycle_date)
        
        # 2. Increment in place
        update_expr = "ADD request_count :inc SET last_request_at = :ts, updated_at = :ts, last_status = :st"
        ts = datetime.now(timezone.utc).isoformat()
        
        updated_item = self.dynamodb.update_item(
            key={"api_source": api_source, "tracking_date": cycle_date},
            update_expression=update_expr,
            expression_values={
                ":inc": 1, 
                ":ts": ts,
                ":st": "success" if success else "failed"
            }
        )
        
        if not updated_item:
            # Fallback: Maybe item expired ms ago? Safe retry logic could go here but minimal simple:
            logger.error(f"Failed to record request for {api_source}")
            return False

        # 3. Log Check
        usage_pct = (updated_item.get("request_count", 0) / updated_item.get("quota_limit", 1)) * 100
        limit = updated_item.get("quota_limit", 0)
        if usage_pct >= 90 and limit < 1000000:
             logger.warning(f"{api_source} monthly quota is {usage_pct:.1f}% used ({updated_item['request_count']}/{limit})")

        return True

    def mark_api_throttled(
        self, 
        api_source: str, 
        date: Optional[str] = None
    ) -> Optional[str]:
        """
        Mark an API as throttled and return the failover API if configured.

        Args:
            api_source: Name of the API
            date: Date string YYYY-MM-DD; defaults to today

        Returns:
            Name of failover API if defined, else None
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        update_expression = "SET #status = :throttled, throttled_at = :timestamp"
        expression_values = {
            ":throttled": "throttled",
            ":timestamp": datetime.now(timezone.utc).isoformat()
        }
        expression_names = {"#status": "status"}

        updated_item = self.dynamodb.update_item(
            key={"api_source": api_source, "tracking_date": date},
            update_expression=update_expression,
            expression_values=expression_values,
            expression_names=expression_names
        )

        if updated_item is None:
            logger.error(f"Failed to mark {api_source} as throttled on {date}")
            return None

        failover_to = updated_item.get("failover_to")
        if failover_to:
            logger.info(f"{api_source} marked as throttled, failing over to {failover_to}")
        else:
            logger.info(f"{api_source} marked as throttled, no failover configured")

        return failover_to
    
    
    def get_usage_stats(self, api: Optional[str] = None, date: Optional[str] = None) -> List[Dict]:
        stats = []
        apis = [api] if api else self.api_priority
        for a in apis:
            item = self._get_active_cycle(a)
            if not item:
                self._initialize_new_cycle(a)
                item = self._get_active_cycle(a)
            
            if item:
                stats.append(self._format_stats(item))
        return stats

    def _initialize_new_cycle(self, api: str, start_date: str = None):
        """Create a new 30-day quota cycle."""
        if not start_date:
            start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            
        cfg = self.apis_config.get(api, {})
        # TTL = 30 days from creation
        ttl_seconds = 30 * 24 * 60 * 60
        ttl_ts = int(datetime.now(timezone.utc).timestamp()) + ttl_seconds
        
        item = {
            "api_source": api,
            "tracking_date": start_date, # Start of Window
            "request_count": 0,
            "quota_limit": cfg.get("quota_limit", 100),
            "quota_period": "monthly_rolling",
            "status": "active",
            "failover_to": cfg.get("failover_to"),
            "priority": cfg.get("priority", 99),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "ttl": ttl_ts 
        }
        self.dynamodb.put_item(item)

    def _format_stats(self, item: Dict) -> Dict:
        request_count = item.get("request_count", 0)
        quota_limit = item.get("quota_limit", 0)
        usage_pct = (request_count / quota_limit * 100) if quota_limit > 0 else 0
        
        # Calculate days remaining in cycle
        ttl = float(item.get("ttl", 0))
        now = datetime.now(timezone.utc).timestamp()
        days_left = max(0, round((ttl - now) / 86400, 1))

        return {
            "api_source": item.get("api_source"),
            "cycle_start": item.get("tracking_date"),
            "created_at": item.get("created_at"),
            "ttl_days_left": days_left,
            "requests": request_count,
            "quota": quota_limit,
            "usage_pct": round(usage_pct, 1),
            "status": item.get("status", "unknown"),
            "remaining": max(0, quota_limit - request_count),
        }

    @staticmethod
    def print_usage_report(stats: List[Dict]):
        for s in stats:
            logger.info(f"{s['api_source']}: {s['requests']}/{s['quota']} reqs, {s['ttl_days_left']} days left in cycle")
