import time


class Cache:
    def __init__(self, expiry=60):
        self.cache = {}
        self.expiry = expiry  # Cache expiry time in seconds

    def set(self, key, value):
        # Store the value along with the expiry time
        self.cache[key] = (value, time.time() + self.expiry)

    def get(self, key):
        # Retrieve a value if it's not expired
        if key in self.cache:
            value, expiry_time = self.cache[key]
            if time.time() < expiry_time:
                return value
            else:
                # If the entry is expired, delete it and return None
                del self.cache[key]
        return None

    def delete(self, key):
        # Delete a cache entry, if it exists
        if key in self.cache:
            del self.cache[key]

    def clear_expired(self):
        # Clear all expired entries from the cache
        current_time = time.time()
        keys_to_delete = [key for key, (_, expiry_time) in self.cache.items() if current_time >= expiry_time]
        for key in keys_to_delete:
            del self.cache[key]
