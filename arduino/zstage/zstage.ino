/*
  openUC2 V2 - continue Z-besturing

  U = omhoog
  D = omlaag
  S = stop
  F = snel
  N = normaal
*/

const int Z_DIR_PIN  = 14;
const int Z_STEP_PIN = 12;
const int ENABLE_PIN = 13;

// lager = sneller
const unsigned long NORMAL_INTERVAL_US = 2000;
const unsigned long FAST_INTERVAL_US   = 250;

unsigned long stepInterval = NORMAL_INTERVAL_US;

bool moving = false;
bool stepState = false;

unsigned long lastStepTime = 0;

void setup() {
  Serial.begin(115200);

  pinMode(Z_DIR_PIN, OUTPUT);
  pinMode(Z_STEP_PIN, OUTPUT);
  pinMode(ENABLE_PIN, OUTPUT);

  digitalWrite(Z_STEP_PIN, LOW);

  // driver inschakelen
  digitalWrite(ENABLE_PIN, LOW);

  Serial.println("Z-STAGE READY");
  Serial.println("U = omhoog");
  Serial.println("D = omlaag");
  Serial.println("S = stop");
  Serial.println("F = snel");
  Serial.println("N = normaal");
}

void loop() {

  // COMMANDO ONTVANGEN
  while (Serial.available() > 0) {

    char command = Serial.read();

    if (command == 'U' || command == 'u') {

      digitalWrite(Z_DIR_PIN, HIGH);
      moving = true;

      Serial.println("UP");
    }

    else if (command == 'D' || command == 'd') {

      digitalWrite(Z_DIR_PIN, LOW);
      moving = true;

      Serial.println("DOWN");
    }

    else if (command == 'S' || command == 's') {

      moving = false;
      digitalWrite(Z_STEP_PIN, LOW);
      stepState = false;

      Serial.println("STOP");
    }

    else if (command == 'F' || command == 'f') {

      stepInterval = FAST_INTERVAL_US;

      Serial.println("FAST");
    }

    else if (command == 'N' || command == 'n') {

      stepInterval = NORMAL_INTERVAL_US;

      Serial.println("NORMAL");
    }
  }


  // MOTOR LATEN DRAAIEN
  if (moving) {

    unsigned long now = micros();

    if (now - lastStepTime >= stepInterval) {

      lastStepTime = now;

      stepState = !stepState;

      digitalWrite(Z_STEP_PIN, stepState);
    }
  }
}