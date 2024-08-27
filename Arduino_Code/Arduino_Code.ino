#pragma GCC optimize ("-Ofast")

#ifndef LED_BUILTIN
#define LED_BUILTIN 13
#endif

#if defined(ARDUINO_ARCH_AVR) || defined(ARDUINO_ARCH_MEGAAVR)
typedef uint32_t uintDiff;
#else
typedef uint32_t uintDiff;
#endif

#include "uniqueID.h"
#include "duco_hash.h"

String get_DUCOID() {
  String ID = "DUCOID";
  char buff[4];
  for (size_t i = 0; i < 8; i++) {
    sprintf(buff, "%02X", (uint8_t)UniqueID8[i]);
    ID += buff;
  }
  return ID;
}

String DUCOID = "";

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  DUCOID = get_DUCOID();
  Serial.begin(115200);
  Serial.setTimeout(10000);
  while (!Serial);
  Serial.flush();
}

void lowercase_hex_to_bytes(const char *hexDigest, uint8_t*rawDigest) {
  for (uint8_t i = 0, j = 0; j < SHA1_HASH_LEN; i += 2, j += 1) {
    rawDigest[j] = (hexDigest[i] > '9' ? hexDigest[i] - 'a' + 10 : hexDigest[i] - '0') << 4 |
                   (hexDigest[i + 1] > '9' ? hexDigest[i + 1] - 'a' + 10 : hexDigest[i + 1] - '0');
  }
}

uintDiff ducos1a(const char *prevBlockHash, const char*targetBlockHash, uintDiff difficulty) {
  if (difficulty > 655) return 0;

  uint8_t target[SHA1_HASH_LEN];
  lowercase_hex_to_bytes(targetBlockHash, target);

  uintDiff maxNonce = difficulty * 100 + 1;
  return ducos1a_mine(prevBlockHash, target, maxNonce);
}

uintDiff ducos1a_mine(const char *prevBlockHash, const uint8_t*target, uintDiff maxNonce) {
  static duco_hash_state_t hash;
  duco_hash_init(&hash, prevBlockHash);

  char nonce

uintDiff ducos1a_mine(const char *prevBlockHash, const uint8_t*target, uintDiff maxNonce) {
  static duco_hash_state_t hash;
  duco_hash_init(&hash, prevBlockHash);

  char nonceStr[10 + 1];
  for (uintDiff nonce = 0; nonce < maxNonce; nonce++) {
    ultoa(nonce, nonceStr, 10);
    uint8_t const *hash_bytes = duco_hash_try_nonce(&hash, nonceStr);
    
    if (memcmp(hash_bytes, target, SHA1_HASH_LEN) == 0) {
      return nonce;  // Return the nonce if the hash matches the target
    }
  }

  return 0;  // Return 0 if no valid nonce is found
}

void loop() {
  if (Serial.available() <= 0) return;

  char lastBlockHash[40 + 1];
  char newBlockHash[40 + 1];

  if (Serial.readBytesUntil(',', lastBlockHash, 41) != 40) return;
  lastBlockHash[40] = 0;

  if (Serial.readBytesUntil(',', newBlockHash, 41) != 40) return;
  newBlockHash[40] = 0;

  uintDiff difficulty = strtoul(Serial.readStringUntil(',').c_str(), NULL, 10);
  while (Serial.available()) Serial.read();  // Clear the receive buffer
  digitalWrite(LED_BUILTIN, LOW);  // Turn on the built-in LED

  uint32_t startTime = micros();
  uintDiff ducos1result = ducos1a(lastBlockHash, newBlockHash, difficulty);
  uint32_t elapsedTime = micros() - startTime;

  digitalWrite(LED_BUILTIN, HIGH);  // Turn off the built-in LED

  while (Serial.available()) Serial.read();  // Clear the receive buffer before sending the result
  Serial.print(String(ducos1result, 2) + "," + String(elapsedTime, 2) + "," + String(DUCOID) + "\n");
}
